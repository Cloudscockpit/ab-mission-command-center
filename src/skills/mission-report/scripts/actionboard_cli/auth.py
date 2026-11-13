"""ActionBoard CLI: auth."""
import base64
import configparser
import getpass
import json
import os
import sys
import time

def decode_jwt_payload(token):
    if not token or not isinstance(token, str):
        return {}
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    payload = parts[1]
    pad = "=" * ((4 - len(payload) % 4) % 4)
    try:
        raw = base64.urlsafe_b64decode((payload + pad).encode("ascii"))
        data = json.loads(raw.decode("utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def token_is_valid(token, skew_seconds=60):
    if not token:
        return False
    claims = decode_jwt_payload(token)
    exp = claims.get("exp")
    if isinstance(exp, (int, float)):
        return time.time() + skew_seconds < exp
    return True


def resolve_settings(cred_path=None, config_path=".actionboard/config.json", args=None):
    from .common import DEFAULT_COGNITO_DOMAIN
    from .common import DEFAULT_EDGE_PROXY_URL
    from .common import DEFAULT_S3_BUCKET
    from .common import DEFAULT_S3_PREFIX
    from .common import DEFAULT_S3_REGION
    from .common import _EDGE_CONTEXT
    from .common import default_credentials_path
    from .common import load_json_file
    cred_file = cred_path or default_credentials_path()
    creds = {}
    if not cred_path:
        home_cred = os.path.join(os.path.expanduser("~"), ".actionboard", "credentials.json")
        local_cred = os.path.abspath(os.path.join(".actionboard", "credentials.json"))
        for candidate in (home_cred, local_cred):
            for k, v in load_json_file(candidate).items():
                if v not in (None, "", {}):
                    creds[k] = v
    else:
        creds = load_json_file(cred_file)
    cfg = load_json_file(config_path)

    endpoint = (
        getattr(args, "endpoint", None)
        or os.environ.get("APPSYNC_GRAPHQL_ENDPOINT")
        or os.environ.get("APPSYNC_URL")
        or cfg.get("appsync_endpoint")
        or creds.get("appsync_endpoint")
    )
    api_key = (
        getattr(args, "api_key", None)
        or os.environ.get("APPSYNC_API_KEY")
        or creds.get("appsync_api_key")
    )
    explicit_edge = os.environ.get("ACTIONBOARD_EDGE_PROXY_URL") or creds.get("edge_proxy_url")
    edge_proxy = ""
    if getattr(args, "api_key", None) is None and (explicit_edge or not api_key):
        # No API key needed: route through the edge proxy. A configured API key keeps the old direct mode.
        edge_proxy = (explicit_edge or DEFAULT_EDGE_PROXY_URL).strip().rstrip("/")
        endpoint = edge_proxy + "/graphql"
        api_key = None

    s3_region = (
        getattr(args, "s3_region", None)
        or os.environ.get("S3_REGION")
        or cfg.get("s3_region")
        or creds.get("s3_region")
        or DEFAULT_S3_REGION
    )
    s3_bucket = (
        getattr(args, "s3_bucket", None)
        or os.environ.get("S3_BUCKET_NAME")
        or cfg.get("s3_bucket")
        or creds.get("s3_bucket")
        or DEFAULT_S3_BUCKET
    )
    s3_prefix = (
        getattr(args, "s3_prefix", None)
        or os.environ.get("S3_PREFIX")
        or cfg.get("s3_prefix")
        or creds.get("s3_prefix")
        or DEFAULT_S3_PREFIX
    ).strip("/")

    settings = {
        "cred_file": cred_file,
        "creds": creds,
        "config_file": config_path,
        "cfg": cfg,
        "endpoint": endpoint,
        "api_key": api_key,
        "edge_proxy": edge_proxy,
        "s3_region": s3_region,
        "s3_bucket": s3_bucket,
        "s3_prefix": s3_prefix,
        "cognito_domain": (
            os.environ.get("COGNITO_DOMAIN")
            or creds.get("cognito_domain")
            or DEFAULT_COGNITO_DOMAIN
        ),
        "cognito_client_id": (
            os.environ.get("COGNITO_CLIENT_ID")
            or creds.get("cognito_client_id")
            or ""
        ),
    }
    _EDGE_CONTEXT["settings"] = settings
    return settings


def resolve_aws_credentials(creds):
    access_key = os.environ.get("AWS_ACCESS_KEY_ID") or creds.get("aws_access_key_id")
    secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY") or creds.get("aws_secret_access_key")
    session_token = os.environ.get("AWS_SESSION_TOKEN") or creds.get("aws_session_token")
    if access_key and secret_key:
        return {
            "access_key": access_key.strip(),
            "secret_key": secret_key.strip(),
            "session_token": session_token.strip() if session_token else None,
        }

    aws_cred_path = os.path.expanduser(
        os.environ.get("AWS_SHARED_CREDENTIALS_FILE", "~/.aws/credentials")
    )
    profile = os.environ.get("AWS_PROFILE") or os.environ.get("AWS_DEFAULT_PROFILE") or "default"
    if os.path.exists(aws_cred_path):
        cp = configparser.ConfigParser()
        try:
            cp.read(aws_cred_path, encoding="utf-8")
            if cp.has_section(profile):
                ak = cp.get(profile, "aws_access_key_id", fallback="").strip()
                sk = cp.get(profile, "aws_secret_access_key", fallback="").strip()
                st = cp.get(profile, "aws_session_token", fallback="").strip() or None
                if ak and sk:
                    return {"access_key": ak, "secret_key": sk, "session_token": st}
        except Exception:
            pass
    return None


def login_with_credentials(settings, email, password, opener=None):
    from .operations import MUTATION_LOGIN
    from .operations import QUERY_ME
    from .common import fail
    from .api import graphql_request
    from .common import save_secure_json
    data = graphql_request(
        settings["endpoint"],
        settings["api_key"],
        MUTATION_LOGIN,
        {"input": {"email": email, "password": password}},
        opener=opener,
    )
    res = data.get("auth_login") or {}
    if not res.get("success"):
        fail("login failed: %s" % (res.get("message") or "unknown error"))

    payload = res.get("data") or {}
    tokens = payload.get("tokens") or {}
    user = payload.get("user") or {}
    access_token = tokens.get("accessToken")
    id_token = tokens.get("idToken")
    if not access_token:
        fail("login response did not include an accessToken")

    profile_id = user.get("profileId")
    if not profile_id and id_token:
        claims = decode_jwt_payload(id_token)
        profile_id = claims.get("custom:profileId")

    if not profile_id:
        try:
            me_data = graphql_request(
                settings["endpoint"],
                settings["api_key"],
                QUERY_ME,
                bearer_token=access_token,
                opener=opener,
            )
            me_user = ((me_data.get("auth_me") or {}).get("data") or {}).get("user") or {}
            profile_id = me_user.get("profileId") or profile_id
        except Exception:
            pass

    creds = dict(settings["creds"])
    if not settings.get("edge_proxy"):
        creds["appsync_endpoint"] = settings["endpoint"]
        creds["appsync_api_key"] = settings["api_key"]
    creds["s3_region"] = settings["s3_region"]
    creds["s3_bucket"] = settings["s3_bucket"]
    creds["s3_prefix"] = settings["s3_prefix"]
    creds["email"] = user.get("email") or email
    creds["user_id"] = user.get("userId") or decode_jwt_payload(id_token).get("sub") or ""
    creds["profile_id"] = profile_id or ""
    creds["name"] = user.get("name") or ""
    creds["access_token"] = access_token
    creds["id_token"] = id_token or ""
    if tokens.get("refreshToken"):
        creds["refresh_token"] = tokens["refreshToken"]
    expires_in = tokens.get("expiresIn") or 3600
    creds["expires_at"] = int(time.time()) + int(expires_in)
    save_secure_json(settings["cred_file"], creds)
    settings["creds"] = creds
    return creds


def get_cached_pod_id_token(settings, pod_id):
    env_pod_token = os.environ.get("ACTIONBOARD_POD_ID_TOKEN")
    if env_pod_token:
        return env_pod_token
    if not pod_id:
        return None
    pod_tokens = (settings.get("creds") or {}).get("pod_tokens") or {}
    cached = pod_tokens.get(pod_id) or {}
    tok = cached.get("id_token")
    if tok and token_is_valid(tok):
        return tok
    return None


def ensure_main_token(settings, interactive=True, opener=None):
    from .operations import MUTATION_REFRESH
    from .common import fail
    from .api import graphql_request
    from .common import info
    from .common import save_secure_json
    env_token = os.environ.get("ACTIONBOARD_ACCESS_TOKEN")
    if env_token:
        return env_token

    creds = settings["creds"]
    access_token = creds.get("access_token")
    if access_token and token_is_valid(access_token):
        return access_token

    refresh_token = creds.get("refresh_token")
    email = os.environ.get("ACTIONBOARD_EMAIL") or creds.get("email")
    jwt_username = decode_jwt_payload(creds.get("id_token")).get("cognito:username")
    username_candidates = []
    for candidate in (email, creds.get("user_id"), jwt_username):
        if candidate and candidate not in username_candidates:
            username_candidates.append(candidate)

    if refresh_token and username_candidates:
        for username in username_candidates:
            try:
                data = graphql_request(
                    settings["endpoint"],
                    settings["api_key"],
                    MUTATION_REFRESH,
                    {"input": {"refreshToken": refresh_token, "username": username}},
                    opener=opener,
                )
                res = data.get("auth_refreshToken") or {}
                if res.get("success"):
                    tokens = (res.get("data") or {}).get("tokens") or {}
                    if tokens.get("accessToken"):
                        creds["access_token"] = tokens["accessToken"]
                        if tokens.get("idToken"):
                            creds["id_token"] = tokens["idToken"]
                        if tokens.get("refreshToken"):
                            creds["refresh_token"] = tokens["refreshToken"]
                        creds["expires_at"] = int(time.time()) + int(tokens.get("expiresIn") or 3600)
                        save_secure_json(settings["cred_file"], creds)
                        return creds["access_token"]
            except Exception:
                pass

    env_password = os.environ.get("ACTIONBOARD_PASSWORD")
    if email and env_password:
        updated = login_with_credentials(settings, email, env_password, opener=opener)
        return updated["access_token"]

    if interactive and sys.stdin.isatty():
        info("ActionBoard login required.")
        prompt_email = input("ActionBoard Email%s: " % (" [%s]" % email if email else "")).strip() or email
        if not prompt_email:
            fail("email is required to log in")
        prompt_pw = getpass.getpass("ActionBoard Password: ")
        if not prompt_pw:
            fail("password is required to log in")
        updated = login_with_credentials(settings, prompt_email, prompt_pw, opener=opener)
        return updated["access_token"]

    fail(
        "not logged in to ActionBoard. Run `python submit_mission.py login` "
        "or set ACTIONBOARD_EMAIL and ACTIONBOARD_PASSWORD."
    )


def fetch_my_pods(settings, main_token, opener=None):
    from .operations import QUERY_MY_PODS
    from .common import fail
    from .api import graphql_request
    data = graphql_request(
        settings["endpoint"],
        settings["api_key"],
        QUERY_MY_PODS,
        bearer_token=main_token,
        opener=opener,
    )
    res = data.get("pods_getMyPods") or {}
    if not res.get("success"):
        fail("failed to fetch pods: %s" % (res.get("message") or "unknown error"))
    return res.get("data") or []


def ensure_pod_id_token(settings, main_token, pod_id, pod_hostname=None, opener=None):
    from .operations import MUTATION_CONSUME_EXCHANGE_CODE
    from .operations import MUTATION_CREATE_EXCHANGE_CODE
    from .common import fail
    from .api import graphql_request
    from .common import save_secure_json
    cached_tok = get_cached_pod_id_token(settings, pod_id)
    if cached_tok:
        return cached_tok

    if not main_token:
        main_token = ensure_main_token(settings, interactive=False, opener=opener)

    creds = settings["creds"]
    pod_tokens = creds.get("pod_tokens") or {}

    if not pod_hostname:
        pods = fetch_my_pods(settings, main_token, opener=opener)
        for p in pods:
            if p.get("podId") == pod_id:
                pod_hostname = p.get("hostname")
                break

    return_url = ("https://%s" % pod_hostname) if pod_hostname else "http://localhost:3000"
    ex_data = graphql_request(
        settings["endpoint"],
        settings["api_key"],
        MUTATION_CREATE_EXCHANGE_CODE,
        {"podId": pod_id, "returnUrl": return_url},
        bearer_token=main_token,
        opener=opener,
    )
    ex_res = ex_data.get("pods_createExchangeCode") or {}
    if not ex_res.get("success"):
        fail("pod token exchange failed for pod %s: %s" % (pod_id, ex_res.get("message") or "unknown error"))

    code = (ex_res.get("data") or {}).get("code")
    if not code:
        fail("pod token exchange did not return a code")

    con_data = graphql_request(
        settings["endpoint"],
        settings["api_key"],
        MUTATION_CONSUME_EXCHANGE_CODE,
        {"code": code, "podId": pod_id},
        bearer_token=main_token,
        opener=opener,
    )
    con_res = con_data.get("pods_consumeExchangeCode") or {}
    if not con_res.get("success"):
        fail("pod token redemption failed for pod %s: %s" % (pod_id, con_res.get("message") or "unknown error"))

    payload = con_res.get("data") or {}
    pod_id_token = payload.get("idToken") or payload.get("token")
    if not pod_id_token:
        fail("pod token redemption did not return an idToken")

    claims = decode_jwt_payload(pod_id_token)
    if claims.get("custom:profileId") and not creds.get("profile_id"):
        creds["profile_id"] = claims["custom:profileId"]

    pod_tokens[pod_id] = {
        "id_token": pod_id_token,
        "access_token": payload.get("accessToken") or "",
        "user_id": payload.get("userId") or claims.get("sub") or "",
        "expires_at": int(time.time()) + int(payload.get("expiresIn") or 3600),
    }
    creds["pod_tokens"] = pod_tokens
    save_secure_json(settings["cred_file"], creds)
    return pod_id_token


