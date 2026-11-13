"""ActionBoard CLI: commands."""
import argparse
import datetime
import getpass
import hashlib
import json
import os
import re
import sys
import time

def prompt_choice(prompt_text, items, label_fn, allow_zero_label=None):
    from .common import fail
    from .common import info
    if allow_zero_label is not None:
        info("  [0] %s" % allow_zero_label)
    for idx, item in enumerate(items, 1):
        info("  [%d] %s" % (idx, label_fn(item)))
    while True:
        try:
            raw = input(prompt_text).strip()
        except EOFError:
            fail("interactive selection cancelled (EOF)")
        if allow_zero_label is not None and raw == "0":
            return None
        if raw.isdigit():
            choice = int(raw)
            if 1 <= choice <= len(items):
                return items[choice - 1]
        info("Please enter a valid number.")


def select_pod_and_board(settings, main_token=None, pod_arg=None, board_arg=None, interactive=True, opener=None):
    from .auth import ensure_main_token
    from .auth import ensure_pod_id_token
    from .common import fail
    from .api import fetch_my_boards
    from .auth import fetch_my_pods
    from .auth import get_cached_pod_id_token
    from .common import info
    from .common import save_config_json
    cfg = settings["cfg"]
    if settings.get("edge_proxy") and not main_token:
        # Every edge request needs the main-pool token, so log in (or refresh) up front.
        main_token = ensure_main_token(settings, interactive=interactive, opener=opener)
    target_pod_id = pod_arg or cfg.get("pod_id")
    cached_pod_token = get_cached_pod_id_token(settings, target_pod_id)

    if cached_pod_token and target_pod_id:
        selected_pod = {
            "podId": target_pod_id,
            "podName": cfg.get("pod_name") if cfg.get("pod_id") == target_pod_id else "",
            "hostname": cfg.get("pod_hostname") if cfg.get("pod_id") == target_pod_id else "",
            "bucketName": cfg.get("pod_bucket") if cfg.get("pod_id") == target_pod_id else "",
        }
        pod_id = target_pod_id
        pod_hostname = selected_pod.get("hostname")
        pod_id_token = cached_pod_token
    else:
        if not main_token:
            main_token = ensure_main_token(settings, interactive=interactive, opener=opener)
        pods = fetch_my_pods(settings, main_token, opener=opener)
        if not pods:
            fail("your ActionBoard account has no pods.")

        selected_pod = None
        if target_pod_id:
            for p in pods:
                if p.get("podId") == target_pod_id or p.get("slug") == target_pod_id or p.get("podName") == target_pod_id:
                    selected_pod = p
                    break
            if not selected_pod and pod_arg:
                fail("pod %r not found in your pods list" % pod_arg)

        if not selected_pod:
            if len(pods) == 1 and not interactive:
                selected_pod = pods[0]
            elif interactive and sys.stdin.isatty():
                info("\nSelect an ActionBoard Pod:")
                selected_pod = prompt_choice(
                    "Pod number: ",
                    pods,
                    lambda p: "%s (%s) — role: %s" % (
                        p.get("podName") or p.get("slug") or p.get("podId"),
                        p.get("podId"),
                        p.get("memberRole") or "member",
                    ),
                )
            else:
                fail("no pod selected. Pass --pod <podId> or run `python submit_mission.py select` interactively.")

        pod_id = selected_pod["podId"]
        pod_hostname = selected_pod.get("hostname")
        pod_id_token = ensure_pod_id_token(settings, main_token, pod_id, pod_hostname=pod_hostname, opener=opener)

    boards = fetch_my_boards(settings, pod_id_token, pod_id=pod_id, opener=opener)
    if not boards:
        fail("no boards found in pod %s (%s)." % (selected_pod.get("podName") or pod_id, pod_id))

    selected_board = None
    target_board_id = board_arg or (cfg.get("board_id") if cfg.get("pod_id") == pod_id else None)
    if target_board_id:
        for b in boards:
            if b.get("boardId") == target_board_id or b.get("name") == target_board_id:
                selected_board = b
                break
        if not selected_board and board_arg:
            fail("board %r not found in pod %s" % (board_arg, pod_id))

    if not selected_board:
        if len(boards) == 1 and not interactive:
            selected_board = boards[0]
        elif interactive and sys.stdin.isatty():
            info("\nSelect a Board in pod '%s':" % (selected_pod.get("podName") or pod_id))
            selected_board = prompt_choice(
                "Board number: ",
                boards,
                lambda b: "%s (%s) — %s" % (
                    b.get("name") or b.get("boardId"),
                    b.get("boardId"),
                    b.get("boardType") or "BOARD",
                ),
            )
        else:
            fail("no board selected. Pass --board <boardId> or run `python submit_mission.py select` interactively.")

    cfg["pod_id"] = pod_id
    if selected_pod.get("podName"):
        cfg["pod_name"] = selected_pod.get("podName")
    if pod_hostname:
        cfg["pod_hostname"] = pod_hostname
    if selected_pod.get("bucketName"):
        cfg["pod_bucket"] = selected_pod["bucketName"]
    cfg["board_id"] = selected_board["boardId"]
    cfg["board_name"] = selected_board.get("name") or ""
    save_config_json(settings["config_file"], cfg)

    return selected_pod, selected_board, pod_id_token


def fallback_upload_via_filemanager(settings, pod_id_token, board_id, mission_id, mission_title, uploaded_reports, opener=None):
    """If assistprofile_submitReports fails because a legacy mission has no missionFolderId,
    create/find the Mission folder in FileManager and register each file via filemanager_createFile.
    """
    from .operations import MUTATION_CREATE_FILE
    from .operations import MUTATION_CREATE_FOLDER
    from .operations import QUERY_FOLDERS_BY_BOARD
    from .common import fail
    from .api import graphql_request
    folder_data = graphql_request(
        settings["endpoint"],
        settings["api_key"],
        QUERY_FOLDERS_BY_BOARD,
        {"boardId": board_id, "first": 100},
        bearer_token=pod_id_token,
        opener=opener,
    )
    folder_conn = ((folder_data.get("filemanager_foldersByBoardIdIndex") or {}).get("data") or {})
    folders = folder_conn.get("items") or []

    short_id = mission_id[:8]
    expected_root_prefix = "Mission: %s" % mission_title
    root_folder_id = None
    reports_folder_id = None

    for f in folders:
        fname = f.get("folderName") or ""
        if fname.startswith(expected_root_prefix) or (short_id in fname and fname.startswith("Mission:")):
            root_folder_id = f.get("id")
            break

    if root_folder_id:
        for f in folders:
            if f.get("parentFolderId") == root_folder_id and f.get("folderName") == "Reports":
                reports_folder_id = f.get("id")
                break

    if not root_folder_id:
        res_root = graphql_request(
            settings["endpoint"],
            settings["api_key"],
            MUTATION_CREATE_FOLDER,
            {
                "input": {
                    "boardId": board_id,
                    "folderName": "Mission: %s (%s)" % (mission_title, short_id),
                    "tags": ["mission", mission_id],
                    "meta": json.dumps({"missionId": mission_id, "type": "mission_root"}),
                    "createdBy": "system",
                }
            },
            bearer_token=pod_id_token,
            opener=opener,
        )
        root_folder = ((res_root.get("filemanager_createFolder") or {}).get("data") or {})
        root_folder_id = root_folder.get("id")

    if root_folder_id and not reports_folder_id:
        res_rep = graphql_request(
            settings["endpoint"],
            settings["api_key"],
            MUTATION_CREATE_FOLDER,
            {
                "input": {
                    "boardId": board_id,
                    "folderName": "Reports",
                    "parentFolderId": root_folder_id,
                    "tags": ["mission", "reports", mission_id],
                    "meta": json.dumps({"missionId": mission_id, "type": "mission_reports"}),
                    "createdBy": "system",
                }
            },
            bearer_token=pod_id_token,
            opener=opener,
        )
        rep_folder = ((res_rep.get("filemanager_createFolder") or {}).get("data") or {})
        reports_folder_id = rep_folder.get("id")

    target_folder_id = reports_folder_id or root_folder_id
    if not target_folder_id:
        fail("could not create or locate mission folder on board %s" % board_id)

    created = []
    for rep in uploaded_reports:
        f_res = graphql_request(
            settings["endpoint"],
            settings["api_key"],
            MUTATION_CREATE_FILE,
            {
                "input": {
                    "boardId": board_id,
                    "folderId": target_folder_id,
                    "fileName": rep["fileName"],
                    "fileType": rep["fileType"],
                    "fileSize": rep["fileSize"],
                    "url": rep["url"],
                    "s3Object": rep["s3Object"],
                    "tags": rep.get("tags"),
                    "note": rep.get("note"),
                    "fileMetaData": json.dumps({"missionId": mission_id}),
                }
            },
            bearer_token=pod_id_token,
            opener=opener,
        )
        f_env = f_res.get("filemanager_createFile") or {}
        if f_env.get("success") and f_env.get("data"):
            created.append(f_env["data"])
    return created


def cmd_configure(args):
    from .common import DEFAULT_S3_BUCKET
    from .common import DEFAULT_S3_PREFIX
    from .common import DEFAULT_S3_REGION
    from .common import default_credentials_path
    from .common import fail
    from .common import info
    from .common import load_credentials
    from .common import save_credentials
    cred_file = args.credentials_file or default_credentials_path()
    creds = load_credentials(cred_file)
    if args.from_env_file:
        if not os.path.exists(args.from_env_file):
            fail("--from-env-file %s does not exist" % args.from_env_file)
        with open(args.from_env_file, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                m = re.match(r"^([A-Z0-9_]+)\s*[:=]\s*(.+)$", line)
                if not m:
                    continue
                k, v = m.group(1).strip(), m.group(2).strip().strip("\"'")
                if k in ("APPSYNC_GRAPHQL_ENDPOINT", "APPSYNC_URL"):
                    creds["appsync_endpoint"] = v
                elif k == "APPSYNC_API_KEY":
                    creds["appsync_api_key"] = v
                elif k == "S3_REGION":
                    creds["s3_region"] = v
                elif k == "S3_BUCKET_NAME":
                    creds["s3_bucket"] = v
                elif k == "S3_PREFIX":
                    creds["s3_prefix"] = v.strip("/")
                elif k == "COGNITO_DOMAIN":
                    creds["cognito_domain"] = v
                elif k == "COGNITO_CLIENT_ID":
                    creds["cognito_client_id"] = v
                elif k == "COGNITO_REDIRECT_URI":
                    creds["cognito_redirect_uri"] = v
                elif k == "AWS_ACCESS_KEY_ID":
                    creds["aws_access_key_id"] = v
                elif k == "AWS_SECRET_ACCESS_KEY":
                    creds["aws_secret_access_key"] = v
                elif k == "AWS_SESSION_TOKEN":
                    creds["aws_session_token"] = v

    if args.edge_proxy_url is not None:
        if args.edge_proxy_url.strip():
            creds["edge_proxy_url"] = args.edge_proxy_url.strip()
        else:
            creds.pop("edge_proxy_url", None)
    if args.endpoint:
        creds["appsync_endpoint"] = args.endpoint.strip()
    if args.api_key:
        creds["appsync_api_key"] = args.api_key.strip()
    if args.s3_region:
        creds["s3_region"] = args.s3_region.strip()
    if args.s3_bucket:
        creds["s3_bucket"] = args.s3_bucket.strip()
    if args.s3_prefix:
        creds["s3_prefix"] = args.s3_prefix.strip().strip("/")
    if args.cognito_domain:
        creds["cognito_domain"] = args.cognito_domain.strip()
    if args.cognito_client_id:
        creds["cognito_client_id"] = args.cognito_client_id.strip()
    if args.aws_access_key_id:
        creds["aws_access_key_id"] = args.aws_access_key_id.strip()
    if args.aws_secret_access_key:
        creds["aws_secret_access_key"] = args.aws_secret_access_key.strip()
    if args.aws_session_token:
        creds["aws_session_token"] = args.aws_session_token.strip()

    creds.setdefault("s3_region", DEFAULT_S3_REGION)
    creds.setdefault("s3_bucket", DEFAULT_S3_BUCKET)
    creds.setdefault("s3_prefix", DEFAULT_S3_PREFIX)
    saved_path = save_credentials(cred_file, creds)
    info("Saved ActionBoard CLI configuration to %s (mode 0600)." % saved_path)
    return 0


def cmd_login(args, opener=None):
    from .common import fail
    from .common import info
    from .auth import login_with_browser
    from .auth import login_with_credentials
    from .auth import resolve_settings
    from . import keychain
    settings = resolve_settings(args.credentials_file, args.config, args)
    password = args.password or os.environ.get("ACTIONBOARD_PASSWORD")

    # Browser sign-in is the default: the password never passes through the CLI or an agent's chat.
    # A password is used only when one is supplied, or when --email is typed in a terminal.
    if not password and (args.browser or args.provider or not args.email or not sys.stdin.isatty()):
        creds = login_with_browser(
            settings,
            provider=args.provider,
            open_browser=not args.no_browser,
            timeout=args.timeout,
            opener=opener,
        )
        info("Logged in as %s (profileId: %s). Tokens stored in the %s."
             % (creds.get("email") or "your account", creds.get("profile_id") or "resolved on pod exchange",
                keychain.describe(load_backend(settings["cred_file"]))))
        return 0

    email = args.email or os.environ.get("ACTIONBOARD_EMAIL") or settings["creds"].get("email")

    if not email:
        if not sys.stdin.isatty():
            fail("--email or ACTIONBOARD_EMAIL is required in non-interactive mode")
        email = input("ActionBoard Email: ").strip()
    if not password:
        if not sys.stdin.isatty():
            fail("--password or ACTIONBOARD_PASSWORD is required in non-interactive mode")
        password = getpass.getpass("ActionBoard Password: ")

    if not email or not password:
        fail("both email and password are required")

    creds = login_with_credentials(settings, email, password, opener=opener)
    info(
        "Logged in as %s (profileId: %s). Tokens stored in the %s."
        % (creds.get("email"), creds.get("profile_id") or "resolved on pod exchange",
           keychain.describe(load_backend(settings["cred_file"])))
    )
    return 0


def load_backend(cred_file):
    """Which store holds the tokens for this credentials file: a keychain backend name, or None for the file."""
    from .common import load_json_file
    return load_json_file(cred_file).get("keychain_backend")


def cmd_logout(args):
    """Remove the stored tokens (from the keychain and the credentials file); keep the other settings."""
    from .common import info
    from .common import load_json_file
    from .common import save_credentials
    from .auth import resolve_settings
    from . import keychain
    settings = resolve_settings(args.credentials_file, args.config, args)
    cleared = []
    for path in {settings["cred_file"], os.path.abspath(os.path.join(".actionboard", "credentials.json"))}:
        data = load_json_file(path)
        if not data:
            continue
        for key in keychain.SECRET_KEYS + ("expires_at",):
            data.pop(key, None)
        save_credentials(path, data)  # no secrets left: also deletes the keychain item it pointed to
        cleared.append(path)
    info("Logged out. Removed stored ActionBoard tokens%s." % ((" for " + ", ".join(sorted(cleared))) if cleared else ""))
    return 0


def cmd_status(args):
    from .operations import SYNC_MODES
    from .auth import get_cached_pod_id_token
    from .common import info
    from .auth import resolve_aws_credentials
    from .auth import resolve_settings
    from .auth import token_is_valid
    from . import keychain
    settings = resolve_settings(args.credentials_file, args.config, args)
    creds = settings["creds"]
    cfg = settings["cfg"]
    aws_creds = resolve_aws_credentials(creds)
    has_main_token = bool(creds.get("access_token") and token_is_valid(creds.get("access_token")))
    has_pod_token = bool(get_cached_pod_id_token(settings, cfg.get("pod_id")))
    has_refresh = bool(creds.get("refresh_token"))
    has_token = has_main_token or has_pod_token or has_refresh

    status_obj = {
        "credentials_file": settings["cred_file"],
        "config_file": settings["config_file"],
        "appsync_configured": bool(settings["endpoint"] and (settings["api_key"] or settings["edge_proxy"])),
        "connection": "edge" if settings["edge_proxy"] else "direct",
        "edge_proxy_url": settings["edge_proxy"],
        "appsync_endpoint": settings["endpoint"] or "",
        "logged_in": has_token,
        "token_storage": keychain.describe(load_backend(settings["cred_file"])) if has_token else "none",
        "has_refresh_token": has_refresh,
        "email": creds.get("email") or "",
        "profile_id": creds.get("profile_id") or "",
        "s3_bucket": settings["s3_bucket"],
        "s3_region": settings["s3_region"],
        "s3_prefix": settings["s3_prefix"],
        "aws_s3_credentials_ready": bool(aws_creds),
        "default_pod_id": cfg.get("pod_id") or "",
        "default_pod_name": cfg.get("pod_name") or "",
        "default_board_id": cfg.get("board_id") or "",
        "default_board_name": cfg.get("board_name") or "",
        "mission_sync": cfg.get("mission_sync") if cfg.get("mission_sync") in SYNC_MODES else "ask",
    }
    if getattr(args, "json", False):
        info(json.dumps(status_obj, indent=2))
        return 0

    info("ActionBoard CLI Status:")
    info("  Credentials file : %s" % status_obj["credentials_file"])
    if settings["edge_proxy"]:
        info("  Connection       : edge proxy %s (no API key needed)" % settings["edge_proxy"])
    else:
        info("  AppSync endpoint : %s (direct, API key)" % (status_obj["appsync_endpoint"] or "NOT SET"))
    info("  Authenticated    : %s%s" % (
        "yes" if has_token else "no",
        (" (%s, profileId=%s)" % (status_obj["email"], status_obj["profile_id"] or "n/a")) if status_obj["email"] else "",
    ))
    info("  Token storage    : %s" % status_obj["token_storage"])
    info("  S3 target        : s3://%s/%s (%s) — AWS creds: %s" % (
        status_obj["s3_bucket"],
        status_obj["s3_prefix"],
        status_obj["s3_region"],
        "ready" if status_obj["aws_s3_credentials_ready"] else "not set (optional: files upload through the %s)" % (
            "edge proxy" if settings["edge_proxy"] else "pod"),
    ))
    info("  Selected Pod     : %s" % (
        ("%s (%s)" % (status_obj["default_pod_name"], status_obj["default_pod_id"]))
        if status_obj["default_pod_id"] else "none"
    ))
    info("  Mission sync     : %s" % status_obj["mission_sync"])
    info("  Selected Board   : %s" % (
        ("%s (%s)" % (status_obj["default_board_name"], status_obj["default_board_id"]))
        if status_obj["default_board_id"] else "none"
    ))
    return 0


def cmd_pods(args, opener=None):
    from .auth import ensure_main_token
    from .auth import fetch_my_pods
    from .common import info
    from .auth import resolve_settings
    settings = resolve_settings(args.credentials_file, args.config, args)
    main_token = ensure_main_token(settings, interactive=not getattr(args, "no_input", False), opener=opener)
    pods = fetch_my_pods(settings, main_token, opener=opener)
    if getattr(args, "json", False):
        info(json.dumps(pods, indent=2))
        return 0
    if not pods:
        info("No pods found for this account.")
        return 0
    info("%-38s  %-24s  %-10s  %s" % ("POD ID", "NAME", "ROLE", "HOSTNAME"))
    for p in pods:
        info("%-38s  %-24s  %-10s  %s" % (
            p.get("podId") or "",
            (p.get("podName") or p.get("slug") or "")[:24],
            p.get("memberRole") or "",
            p.get("hostname") or "",
        ))
    return 0


def cmd_boards(args, opener=None):
    from .auth import ensure_main_token
    from .auth import ensure_pod_id_token
    from .common import fail
    from .api import fetch_my_boards
    from .auth import fetch_my_pods
    from .auth import get_cached_pod_id_token
    from .common import info
    from .auth import resolve_settings
    settings = resolve_settings(args.credentials_file, args.config, args)
    interactive = not getattr(args, "no_input", False)
    pod_id = args.pod or settings["cfg"].get("pod_id")
    pod_id_token = get_cached_pod_id_token(settings, pod_id)
    if not pod_id_token:
        main_token = ensure_main_token(settings, interactive=interactive, opener=opener)
        if not pod_id:
            pods = fetch_my_pods(settings, main_token, opener=opener)
            if len(pods) == 1:
                pod_id = pods[0]["podId"]
            else:
                fail("pass --pod <podId> or run `python submit_mission.py select` first")
        pod_id_token = ensure_pod_id_token(settings, main_token, pod_id, opener=opener)
    boards = fetch_my_boards(settings, pod_id_token, pod_id=pod_id, search_term=args.search, opener=opener)
    if getattr(args, "json", False):
        info(json.dumps(boards, indent=2))
        return 0
    if not boards:
        info("No boards found in pod %s." % pod_id)
        return 0
    info("%-38s  %-28s  %-10s  %s" % ("BOARD ID", "NAME", "TYPE", "STATUS"))
    for b in boards:
        info("%-38s  %-28s  %-10s  %s" % (
            b.get("boardId") or "",
            (b.get("name") or "")[:28],
            b.get("boardType") or "",
            b.get("boardStatus") or "",
        ))
    return 0


def cmd_missions(args, opener=None):
    from .operations import MUTATION_DELETE_MISSION
    from .auth import ensure_main_token
    from .auth import ensure_pod_id_token
    from .common import fail
    from .api import fetch_missions_by_board
    from .auth import get_cached_pod_id_token
    from .api import graphql_request
    from .common import info
    from .auth import resolve_settings
    settings = resolve_settings(args.credentials_file, args.config, args)
    interactive = not getattr(args, "no_input", False)
    pod_id = args.pod or settings["cfg"].get("pod_id")
    board_id = args.board or settings["cfg"].get("board_id")
    if not pod_id or not board_id:
        fail("pass --pod <podId> and --board <boardId>, or run `python submit_mission.py select` first")
    pod_id_token = get_cached_pod_id_token(settings, pod_id)
    if not pod_id_token:
        main_token = ensure_main_token(settings, interactive=interactive, opener=opener)
        pod_id_token = ensure_pod_id_token(settings, main_token, pod_id, opener=opener)

    if getattr(args, "delete", None):
        graphql_request(
            settings["endpoint"],
            settings["api_key"],
            MUTATION_DELETE_MISSION,
            {"boardId": board_id, "missionId": args.delete},
            bearer_token=pod_id_token,
            opener=opener,
        )
        info("Deleted mission %s from board %s." % (args.delete, board_id))
        return 0

    missions = fetch_missions_by_board(settings, pod_id_token, board_id, opener=opener)
    if getattr(args, "json", False):
        info(json.dumps(missions, indent=2))
        return 0
    if not missions:
        info("No missions found on board %s." % board_id)
        return 0
    info("%-38s  %-12s  %-6s  %s" % ("MISSION ID", "STATUS", "FILES", "TITLE"))
    for m in missions:
        info("%-38s  %-12s  %-6s  %s" % (
            m.get("missionId") or "",
            m.get("status") or "",
            str(m.get("totalFiles") if m.get("totalFiles") is not None else 0),
            m.get("title") or "",
        ))
    return 0


def _resolve_pod_token_and_profile(settings, main_token=None, pod_arg=None, interactive=True, opener=None):
    from .auth import decode_jwt_payload
    from .auth import ensure_main_token
    from .auth import ensure_pod_id_token
    from .common import fail
    from .auth import fetch_my_pods
    from .auth import get_cached_pod_id_token
    from .common import info
    cfg = settings["cfg"]
    if settings.get("edge_proxy") and not main_token:
        # Every edge request needs the main-pool token, so log in (or refresh) up front.
        main_token = ensure_main_token(settings, interactive=interactive, opener=opener)
    target_pod_id = pod_arg or cfg.get("pod_id")
    cached_pod_token = get_cached_pod_id_token(settings, target_pod_id)

    if cached_pod_token and target_pod_id:
        selected_pod = {
            "podId": target_pod_id,
            "podName": cfg.get("pod_name") if cfg.get("pod_id") == target_pod_id else "",
            "hostname": cfg.get("pod_hostname") if cfg.get("pod_id") == target_pod_id else "",
            "bucketName": cfg.get("pod_bucket") if cfg.get("pod_id") == target_pod_id else "",
        }
        pod_id_token = cached_pod_token
    else:
        if not main_token:
            main_token = ensure_main_token(settings, interactive=interactive, opener=opener)
        pods = fetch_my_pods(settings, main_token, opener=opener)
        if not pods:
            fail("your ActionBoard account has no pods.")

        selected_pod = None
        if target_pod_id:
            for p in pods:
                if p.get("podId") == target_pod_id or p.get("slug") == target_pod_id or p.get("podName") == target_pod_id:
                    selected_pod = p
                    break
            if not selected_pod and pod_arg:
                fail("pod %r not found in your pods list" % pod_arg)

        if not selected_pod:
            if len(pods) == 1 or not interactive or not sys.stdin.isatty():
                selected_pod = pods[0]
            else:
                info("\nSelect an ActionBoard Pod:")
                selected_pod = prompt_choice(
                    "Pod number: ",
                    pods,
                    lambda p: "%s (%s) — role: %s" % (
                        p.get("podName") or p.get("slug") or p.get("podId"),
                        p.get("podId"),
                        p.get("memberRole") or "member",
                    ),
                )

        pod_id = selected_pod["podId"]
        pod_id_token = ensure_pod_id_token(
            settings, main_token, pod_id, pod_hostname=selected_pod.get("hostname"), opener=opener
        )

    profile_id = (
        settings["creds"].get("profile_id")
        or decode_jwt_payload(pod_id_token).get("custom:profileId")
        or ""
    )
    return selected_pod, pod_id_token, profile_id


def cmd_assigned(args, opener=None):
    from .api import fetch_missions_by_agent
    from .api import fetch_missions_by_board
    from .api import fetch_my_invitations
    from .common import info
    from .auth import resolve_settings
    settings = resolve_settings(args.credentials_file, args.config, args)
    interactive = not getattr(args, "no_input", False) and sys.stdin.isatty()
    pod, pod_id_token, profile_id = _resolve_pod_token_and_profile(
        settings, None, pod_arg=args.pod, interactive=interactive, opener=opener
    )
    board_filter = args.board or settings["cfg"].get("board_id")

    assigned_missions = []
    if profile_id:
        try:
            assigned_missions = fetch_missions_by_agent(settings, pod_id_token, profile_id, opener=opener)
        except Exception:
            assigned_missions = []

    if board_filter and not assigned_missions:
        board_missions = fetch_missions_by_board(settings, pod_id_token, board_filter, opener=opener)
        for m in board_missions:
            if not profile_id or m.get("assignedAgentProfileId") == profile_id or m.get("selectedProfileId") == profile_id:
                assigned_missions.append(m)
    elif args.board:
        assigned_missions = [m for m in assigned_missions if m.get("boardId") == args.board]

    invitations = []
    try:
        invitations = fetch_my_invitations(
            settings, pod_id_token, status=getattr(args, "invitation_status", None), opener=opener
        )
        if args.board:
            invitations = [inv for inv in invitations if inv.get("boardId") == args.board]
    except Exception:
        invitations = []

    if getattr(args, "json", False):
        info(json.dumps({
            "pod_id": pod["podId"],
            "profile_id": profile_id,
            "assigned_missions": assigned_missions,
            "invitations": invitations,
        }, indent=2))
        return 0

    if not assigned_missions and not invitations:
        info("No missions or invitations currently assigned to profile %s in pod %s." % (profile_id or "current user", pod["podId"]))
        return 0

    if assigned_missions:
        info("Assigned Missions (%d):" % len(assigned_missions))
        info("%-38s  %-38s  %-12s  %s" % ("MISSION ID", "BOARD ID", "STATUS", "TITLE"))
        for m in assigned_missions:
            info("%-38s  %-38s  %-12s  %s" % (
                m.get("missionId") or "",
                m.get("boardId") or "",
                m.get("status") or "",
                m.get("title") or "",
            ))
    if invitations:
        if assigned_missions:
            info("")
        info("Mission Invitations (%d):" % len(invitations))
        info("%-38s  %-38s  %-12s  %s" % ("INVITATION ID", "MISSION ID", "STATUS", "BOARD ID"))
        for inv in invitations:
            info("%-38s  %-38s  %-12s  %s" % (
                inv.get("invitationId") or "",
                inv.get("missionId") or "",
                inv.get("status") or "",
                inv.get("boardId") or "",
            ))
    return 0


def cmd_fetch(args, opener=None):
    """Fetch an assigned (or selected) mission's Brief and Plan from ActionBoard to local disk."""
    from .common import MISSION_FILES
    from .operations import MUTATION_ACCEPT_MISSION_INVITATION
    from .operations import MUTATION_UPDATE_MISSION_STATUS
    from .operations import QUERY_GET_MISSION_INVITATION
    from .operations import QUERY_GET_MISSION_PLAN
    from .storage import download_bytes_from_s3
    from .api import download_bytes_via_edge
    from .common import fail
    from .api import fetch_files_by_board_and_folder
    from .api import fetch_mission
    from .api import fetch_mission_plans
    from .api import fetch_missions_by_agent
    from .api import fetch_missions_by_board
    from .api import fetch_my_invitations
    from .api import graphql_request
    from .common import info
    from .documents import materialize_fetched_mission_docs
    from .auth import resolve_aws_credentials
    from .auth import resolve_settings
    from .common import save_config_json
    from .documents import slugify_title
    from .common import warn
    settings = resolve_settings(args.credentials_file, args.config, args)
    interactive = not getattr(args, "no_input", False) and sys.stdin.isatty()
    pod, pod_id_token, profile_id = _resolve_pod_token_and_profile(
        settings, None, pod_arg=args.pod, interactive=interactive, opener=opener
    )
    pod_id = pod["podId"]
    cfg = settings["cfg"]
    board_id = args.board or cfg.get("board_id")
    mission_id = args.mission_id
    invitation_id = args.invitation_id
    selected_mission = None

    if invitation_id and not mission_id:
        if not board_id:
            invs = fetch_my_invitations(settings, pod_id_token, opener=opener)
            for inv in invs:
                if inv.get("invitationId") == invitation_id:
                    board_id = inv.get("boardId")
                    mission_id = inv.get("missionId")
                    break
        if board_id and not mission_id:
            inv_data = graphql_request(
                settings["endpoint"],
                settings["api_key"],
                QUERY_GET_MISSION_INVITATION,
                {"invitationId": invitation_id, "boardId": board_id},
                bearer_token=pod_id_token,
                opener=opener,
            )
            inv_obj = inv_data.get("assistprofile_getMissionInvitation") or {}
            mission_id = inv_obj.get("missionId")

    if not mission_id:
        candidates = []
        if profile_id:
            try:
                for m in fetch_missions_by_agent(settings, pod_id_token, profile_id, opener=opener):
                    if not args.board or m.get("boardId") == args.board:
                        candidates.append({"kind": "assigned", "mission": m, "invitation": None})
            except Exception:
                pass
        try:
            for inv in fetch_my_invitations(settings, pod_id_token, opener=opener):
                if inv.get("status") in ("PENDING", "ACCEPTED") and (not args.board or inv.get("boardId") == args.board):
                    if not any(c["mission"].get("missionId") == inv.get("missionId") for c in candidates if c.get("mission")):
                        m_obj = fetch_mission(settings, pod_id_token, inv["boardId"], inv["missionId"], opener=opener)
                        if m_obj:
                            candidates.append({"kind": "invitation", "mission": m_obj, "invitation": inv})
        except Exception:
            pass

        if not candidates and board_id:
            for m in fetch_missions_by_board(settings, pod_id_token, board_id, opener=opener):
                candidates.append({"kind": "board", "mission": m, "invitation": None})

        if not candidates:
            fail("no assigned missions or invitations found. Pass --board <boardId> --mission-id <missionId>.")

        if len(candidates) == 1 or not interactive:
            picked = candidates[0]
        else:
            info("\nSelect a Mission to fetch:")
            picked = prompt_choice(
                "Mission number: ",
                candidates,
                lambda c: "[%s] %s (missionId: %s, boardId: %s, status: %s)" % (
                    "INVITED:" + c["invitation"].get("status", "") if c["kind"] == "invitation" else c["kind"].upper(),
                    c["mission"].get("title") or "Untitled",
                    c["mission"].get("missionId"),
                    c["mission"].get("boardId"),
                    c["mission"].get("status") or "INITIATED",
                ),
            )
        selected_mission = picked["mission"]
        mission_id = selected_mission["missionId"]
        board_id = selected_mission["boardId"]
        if picked.get("invitation") and not invitation_id:
            invitation_id = picked["invitation"].get("invitationId")

    if not selected_mission:
        if not board_id:
            # Try locating boardId from assigned missions or invitations
            if profile_id:
                for m in fetch_missions_by_agent(settings, pod_id_token, profile_id, opener=opener):
                    if m.get("missionId") == mission_id:
                        selected_mission = m
                        board_id = m.get("boardId")
                        break
        if not selected_mission and board_id:
            selected_mission = fetch_mission(settings, pod_id_token, board_id, mission_id, opener=opener)
        if not selected_mission:
            fail("could not find mission %s (pass --board <boardId>)" % mission_id)

    if invitation_id and getattr(args, "accept", False):
        acc_data = graphql_request(
            settings["endpoint"],
            settings["api_key"],
            MUTATION_ACCEPT_MISSION_INVITATION,
            {"invitationId": invitation_id, "boardId": board_id},
            bearer_token=pod_id_token,
            opener=opener,
        )
        acc = acc_data.get("assistprofile_acceptMissionInvitation") or {}
        info("Accepted mission invitation %s (status: %s)." % (invitation_id, acc.get("status") or "ACCEPTED"))

    # Fetch MissionPlan(s) for this mission
    selected_plan = None
    if getattr(args, "plan_id", None):
        p_data = graphql_request(
            settings["endpoint"],
            settings["api_key"],
            QUERY_GET_MISSION_PLAN,
            {"missionId": mission_id, "planId": args.plan_id},
            bearer_token=pod_id_token,
            opener=opener,
        )
        selected_plan = p_data.get("assistprofile_getMissionPlan")
    else:
        plans = fetch_mission_plans(settings, pod_id_token, mission_id, opener=opener)
        if plans:
            sel_plan_id = selected_mission.get("selectedPlanId")
            for p in plans:
                if sel_plan_id and p.get("planId") == sel_plan_id:
                    selected_plan = p
                    break
            if not selected_plan and profile_id:
                for p in plans:
                    if p.get("assignedAgentProfileId") == profile_id or p.get("createdByProfileId") == profile_id:
                        selected_plan = p
                        break
            if not selected_plan:
                selected_plan = plans[0]

    # Check if the mission folder on the board has attached files (e.g. mission-brief.md, mission-plan.md)
    downloaded_files = {}
    aws_creds = resolve_aws_credentials(settings["creds"])
    for folder_key in ("missionFolderId", "reportsSubfolderId"):
        folder_id = selected_mission.get(folder_key)
        if not folder_id:
            continue
        folder_files = fetch_files_by_board_and_folder(settings, pod_id_token, board_id, folder_id, opener=opener)
        for fitem in folder_files:
            fname = fitem.get("fileName") or ""
            # Strip optional `<timestamp>-` prefix if present
            clean_name = re.sub(r"^\d{10,}-", "", fname)
            if clean_name in dict((m[0], True) for m in MISSION_FILES) and clean_name not in downloaded_files:
                s3_obj = fitem.get("s3Object") or {}
                if (aws_creds or settings.get("edge_proxy")) and s3_obj.get("bucket") and s3_obj.get("key"):
                    try:
                        if aws_creds:
                            raw_bytes = download_bytes_from_s3(
                                s3_obj["bucket"],
                                s3_obj.get("region") or settings["s3_region"],
                                s3_obj["key"],
                                aws_creds,
                                opener=opener,
                            )
                        else:
                            raw_bytes = download_bytes_via_edge(settings, s3_obj["bucket"], s3_obj["key"], opener=opener)
                        downloaded_files[clean_name] = raw_bytes
                    except Exception as exc:
                        warn("could not download %s from S3: %s" % (clean_name, exc))

    slug = slugify_title(selected_mission.get("title"), mission_id)
    date_prefix = (selected_mission.get("startDate") or selected_mission.get("createdAt") or "")[:10]
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_prefix):
        date_prefix = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

    out_dir = args.out_dir or os.path.join("docs", "missions", "%s-%s" % (date_prefix, slug))
    written_files = materialize_fetched_mission_docs(
        out_dir, slug, selected_mission, plan_obj=selected_plan, downloaded_files=downloaded_files
    )

    if getattr(args, "start", False):
        try:
            graphql_request(
                settings["endpoint"],
                settings["api_key"],
                MUTATION_UPDATE_MISSION_STATUS,
                {"input": {"boardId": board_id, "missionId": mission_id, "status": "IN_PROGRESS"}},
                bearer_token=pod_id_token,
                opener=opener,
            )
            selected_mission["status"] = "IN_PROGRESS"
            info("Marked mission %s as IN_PROGRESS." % mission_id)
        except Exception as exc:
            warn("could not update mission status to IN_PROGRESS: %s" % exc)

    # Save Pod, Board, and Mission linkage to .actionboard/config.json
    cfg["pod_id"] = pod_id
    cfg["pod_name"] = pod.get("podName") or ""
    cfg["board_id"] = board_id
    missions_map = cfg.get("missions") if isinstance(cfg.get("missions"), dict) else {}
    missions_map[slug] = {
        "mission_id": mission_id,
        "plan_id": (selected_plan or {}).get("planId") or "",
        "invitation_id": invitation_id or "",
        "board_id": board_id,
        "pod_id": pod_id,
        "title": selected_mission.get("title") or slug,
        "mission_dir": out_dir,
        "fetched_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    cfg["missions"] = missions_map
    save_config_json(settings["config_file"], cfg)

    fetch_summary = {
        "success": True,
        "pod_id": pod_id,
        "board_id": board_id,
        "mission_id": mission_id,
        "plan_id": (selected_plan or {}).get("planId") or "",
        "invitation_id": invitation_id or "",
        "slug": slug,
        "title": selected_mission.get("title") or "",
        "status": selected_mission.get("status") or "",
        "mission_dir": os.path.abspath(out_dir),
        "files_written": written_files,
    }
    if getattr(args, "json", False):
        info(json.dumps(fetch_summary, indent=2))
    else:
        info("\n=== Fetched Assigned Mission ===")
        info("  Title        : %s" % fetch_summary["title"])
        info("  Mission ID   : %s (status: %s)" % (mission_id, fetch_summary["status"]))
        info("  Board ID     : %s (Pod: %s)" % (board_id, pod_id))
        info("  Plan ID      : %s" % (fetch_summary["plan_id"] or "synthesized from mission metadata"))
        info("  Local Folder : %s" % fetch_summary["mission_dir"])
        info("  Files Ready  : %s" % ", ".join(written_files))
        info("\nNext step: review %s/mission-brief.md and %s/mission-plan.md, start your work, and run `submit_mission.py submit --mission-dir %s` when complete." % (out_dir, out_dir, out_dir))
    return 0


def cmd_select(args, opener=None):
    from .auth import ensure_main_token
    from .common import info
    from .auth import resolve_settings
    from .common import save_config_json
    settings = resolve_settings(args.credentials_file, args.config, args)
    cfg = settings["cfg"]
    if args.sync and not args.pod and not args.board and cfg.get("board_id"):
        cfg["mission_sync"] = args.sync
        save_config_json(settings["config_file"], cfg)
        info("Mission sync set to %s." % args.sync)
        return 0
    main_token = ensure_main_token(settings, interactive=True, opener=opener)
    pod, board, _ = select_pod_and_board(
        settings,
        main_token,
        pod_arg=args.pod,
        board_arg=args.board,
        interactive=True,
        opener=opener,
    )
    info(
        "Saved selection to %s: Pod '%s' (%s) -> Board '%s' (%s)."
        % (
            settings["config_file"],
            pod.get("podName") or pod["podId"],
            pod["podId"],
            board.get("name") or board["boardId"],
            board["boardId"],
        )
    )
    if args.sync:
        settings["cfg"]["mission_sync"] = args.sync
        save_config_json(settings["config_file"], settings["cfg"])
        info("Mission sync set to %s." % args.sync)
    return 0


def find_linked_mission(missions_map, mission_dir, slug):
    """Find the board link for a local mission folder: by its saved folder path first, then by slug."""
    target = os.path.abspath(mission_dir) if mission_dir else None
    for key, entry in missions_map.items():
        if isinstance(entry, dict) and target and entry.get("mission_dir") and os.path.abspath(entry["mission_dir"]) == target:
            return key, entry
    entry = missions_map.get(slug)
    return slug, (entry if isinstance(entry, dict) else {})


def list_mission_files(settings, pod_id_token, board_id, mission_id, opener=None):
    from .operations import QUERY_LIST_MISSION_FILES
    from .operations import QUERY_LIST_MISSION_FILES_PAGE
    from .api import graphql_request
    files, next_token = [], None
    for _ in range(20):  # shortcut: stops after 20 pages (1,000 files); missions hold a handful
        variables = {"missionId": mission_id, "boardId": board_id, "limit": 50}
        if next_token:
            variables["nextToken"] = next_token
        data = graphql_request(
            settings["endpoint"], settings["api_key"],
            QUERY_LIST_MISSION_FILES_PAGE if next_token else QUERY_LIST_MISSION_FILES, variables,
            bearer_token=pod_id_token, opener=opener,
        )
        res = data.get("assistprofile_listMissionFiles") or {}
        if not res.get("success"):
            raise RuntimeError(res.get("message") or "listMissionFiles returned success=false")
        files.extend(res.get("items") or [])
        next_token = res.get("nextToken")
        if not next_token:
            break
    return files


def is_cli_file(existing, local_file, mission_id):
    """True only for a file this CLI registered for the same local file name.

    Files people uploaded through the web or mobile app never carry the CLI tag or the CLI's exact
    note and tag list, so they are never replaced. The second check covers uploads made before the tag existed.
    """
    from .operations import CLI_FILE_TAG
    if existing.get("fileName") != local_file["fileName"]:
        return False
    tags = existing.get("tags") or []
    if CLI_FILE_TAG in tags:
        return True
    return tags == local_file["tags"] + [mission_id] and existing.get("note") == local_file["note"]


def plan_file_sync(files_to_upload, existing_files, mission_id, hashes, replace=True):
    """Split local files into (to_upload, unchanged, file ids to delete after the upload succeeds)."""
    to_upload, unchanged, to_delete = [], [], []
    for f in files_to_upload:
        owned = [e for e in existing_files if is_cli_file(e, f, mission_id)]
        same = [e for e in owned if "sha256:%s" % hashes[f["fileName"]] in (e.get("tags") or [])]
        if same:
            unchanged.append(f)
            stale = [e for e in owned if e is not same[0]]
        else:
            to_upload.append(f)
            stale = owned
        if replace:
            to_delete.extend(e["id"] for e in stale if e.get("id"))
    return to_upload, unchanged, to_delete


def cmd_submit(args, opener=None):
    from .operations import CLI_FILE_TAG
    from .operations import MUTATION_CREATE_MISSION
    from .operations import MUTATION_CREATE_MISSION_PLAN
    from .operations import MUTATION_DELETE_MISSION_FILE
    from .operations import MUTATION_SUBMIT_MISSION_PLAN
    from .operations import MUTATION_SUBMIT_REPORTS
    from .operations import MUTATION_UPDATE_MISSION
    from .operations import MUTATION_UPDATE_MISSION_PLAN
    from .operations import MUTATION_UPDATE_MISSION_STATUS
    from .operations import QUERY_GET_MISSION_INVITATION
    from .documents import build_plan_markdown
    from .documents import collect_mission_files
    from .auth import decode_jwt_payload
    from .auth import ensure_main_token
    from .common import fail
    from .api import fetch_missions_by_board
    from .auth import fetch_my_pods
    from .documents import find_latest_mission_dir
    from .api import graphql_request
    from .common import info
    from .documents import parse_mission_metadata
    from .auth import resolve_aws_credentials
    from .auth import resolve_settings
    from .common import save_config_json
    from .storage import upload_bytes_to_s3
    from .api import upload_bytes_via_edge
    from .storage import upload_bytes_via_pod
    from .common import warn
    settings = resolve_settings(args.credentials_file, args.config, args)
    interactive = not getattr(args, "no_input", False) and sys.stdin.isatty()

    mission_dir = args.mission_dir
    if not mission_dir:
        mission_dir = find_latest_mission_dir(".")
        if not mission_dir:
            fail("could not auto-detect a mission directory. Pass --mission-dir <path>.")
    if not os.path.isdir(mission_dir):
        fail("--mission-dir %s does not exist or is not a directory" % mission_dir)

    meta = parse_mission_metadata(mission_dir)
    title = args.title or meta["title"]
    short_description = args.description or meta["short_description"]
    plan_markdown = build_plan_markdown(mission_dir)
    files_to_upload = collect_mission_files(mission_dir)

    if not plan_markdown and not files_to_upload:
        fail("no mission documents (brief, plan, or report) found in %s" % mission_dir)

    if args.dry_run:
        summary = {
            "dry_run": True,
            "mission_dir": os.path.abspath(mission_dir),
            "slug": meta["slug"],
            "title": title,
            "short_description": short_description,
            "has_plan_markdown": bool(plan_markdown),
            "plan_markdown_bytes": len(plan_markdown.encode("utf-8")),
            "files": [f["fileName"] for f in files_to_upload],
            "s3_bucket": settings["s3_bucket"],
            "s3_region": settings["s3_region"],
            "s3_prefix": settings["s3_prefix"],
        }
        info(json.dumps(summary, indent=2))
        return 0

    pod, board, pod_id_token = select_pod_and_board(
        settings,
        None,
        pod_arg=args.pod,
        board_arg=args.board,
        interactive=interactive,
        opener=opener,
    )
    pod_id = pod["podId"]
    board_id = board["boardId"]
    pod_hostname = pod.get("hostname") or ""
    pod_bucket = pod.get("bucketName") or ""
    profile_id = (
        args.assigned_agent
        or settings["creds"].get("profile_id")
        or decode_jwt_payload(pod_id_token).get("custom:profileId")
        or ""
    )

    cfg = settings["cfg"]
    missions_map = cfg.get("missions") if isinstance(cfg.get("missions"), dict) else {}
    link_key, saved_entry = find_linked_mission(missions_map, mission_dir, meta["slug"])

    mission_id = args.mission_id
    if not mission_id and saved_entry.get("board_id") == board_id:
        mission_id = saved_entry.get("mission_id")

    invitation = None
    if args.invitation_id:
        inv_data = graphql_request(
            settings["endpoint"],
            settings["api_key"],
            QUERY_GET_MISSION_INVITATION,
            {"invitationId": args.invitation_id, "boardId": board_id},
            bearer_token=pod_id_token,
            opener=opener,
        )
        invitation = inv_data.get("assistprofile_getMissionInvitation")
        if not invitation:
            fail("invitation %s not found on board %s" % (args.invitation_id, board_id))
        if not mission_id:
            mission_id = invitation.get("missionId")

    existing_missions = []
    if not mission_id and not args.create_mission:
        existing_missions = fetch_missions_by_board(settings, pod_id_token, board_id, opener=opener)
        for m in existing_missions:
            if (m.get("title") or "").strip().lower() == title.strip().lower():
                mission_id = m.get("missionId")
                break

        if not mission_id and existing_missions and interactive:
            info("\nSelect a Mission on board '%s' (%s):" % (board.get("name") or board_id, board_id))
            chosen = prompt_choice(
                "Mission number (0 to create new): ",
                existing_missions,
                lambda m: "%s (%s) [%s]" % (
                    m.get("title") or "Untitled",
                    m.get("missionId"),
                    m.get("status") or "INITIATED",
                ),
                allow_zero_label="Create new mission: '%s'" % title,
            )
            if chosen:
                mission_id = chosen["missionId"]

    created_new_mission = False
    if not mission_id:
        create_input = {
            "boardId": board_id,
            "title": title,
            "shortDescription": short_description,
        }
        if profile_id:
            create_input["assignedAgentProfileId"] = profile_id
        if meta.get("start_date"):
            create_input["startDate"] = meta["start_date"]
        if meta.get("end_date"):
            create_input["endDate"] = meta["end_date"]

        c_data = graphql_request(
            settings["endpoint"],
            settings["api_key"],
            MUTATION_CREATE_MISSION,
            {"input": create_input},
            bearer_token=pod_id_token,
            opener=opener,
        )
        c_mission = c_data.get("assistprofile_createMission") or {}
        mission_id = c_mission.get("missionId")
        if not mission_id:
            fail("failed to create mission on board %s" % board_id)
        created_new_mission = True
        info("Created mission '%s' (missionId: %s) on board %s." % (title, mission_id, board_id))
    elif args.update_mission:
        update_input = {
            "missionId": mission_id,
            "boardId": board_id,
            "title": title,
            "shortDescription": short_description,
        }
        if profile_id:
            update_input["assignedAgentProfileId"] = profile_id
        graphql_request(
            settings["endpoint"],
            settings["api_key"],
            MUTATION_UPDATE_MISSION,
            {"input": update_input},
            bearer_token=pod_id_token,
            opener=opener,
        )
        info("Updated mission metadata for missionId %s." % mission_id)

    plan_id = args.plan_id or (saved_entry.get("plan_id") if saved_entry.get("mission_id") == mission_id else None)
    effective_invitation_id = args.invitation_id or (
        saved_entry.get("invitation_id") if saved_entry.get("mission_id") == mission_id and not plan_id else None
    )
    if plan_markdown and not args.skip_plan:
        if effective_invitation_id:
            p_data = graphql_request(
                settings["endpoint"],
                settings["api_key"],
                MUTATION_SUBMIT_MISSION_PLAN,
                {
                    "input": {
                        "missionId": mission_id,
                        "invitationId": effective_invitation_id,
                        "boardId": board_id,
                        "plan": plan_markdown,
                    }
                },
                bearer_token=pod_id_token,
                opener=opener,
            )
            plan_obj = p_data.get("assistprofile_submitMissionPlan") or {}
            plan_id = plan_obj.get("planId") or plan_id
            info("Submitted mission plan for invitation %s (planId: %s)." % (effective_invitation_id, plan_id))
        elif plan_id:
            upd_input = {
                "missionId": mission_id,
                "planId": plan_id,
                "boardId": board_id,
                "plan": plan_markdown,
            }
            if profile_id:
                upd_input["assignedAgentProfileId"] = profile_id
            p_data = graphql_request(
                settings["endpoint"],
                settings["api_key"],
                MUTATION_UPDATE_MISSION_PLAN,
                {"input": upd_input},
                bearer_token=pod_id_token,
                opener=opener,
            )
            plan_obj = p_data.get("assistprofile_updateMissionPlan") or {}
            plan_id = plan_obj.get("planId") or plan_id
            info("Updated mission plan (planId: %s)." % plan_id)
        else:
            create_plan_input = {
                "missionId": mission_id,
                "boardId": board_id,
                "plan": plan_markdown,
            }
            if profile_id:
                create_plan_input["assignedAgentProfileId"] = profile_id
            p_data = graphql_request(
                settings["endpoint"],
                settings["api_key"],
                MUTATION_CREATE_MISSION_PLAN,
                {"input": create_plan_input},
                bearer_token=pod_id_token,
                opener=opener,
            )
            plan_obj = p_data.get("assistprofile_createMissionPlan") or {}
            plan_id = plan_obj.get("planId")
            info("Created mission plan on board (planId: %s)." % plan_id)

    def save_link():
        entry = dict(saved_entry) if saved_entry.get("mission_id") == mission_id else {}
        entry.update({
            "mission_id": mission_id,
            "plan_id": plan_id or "",
            "board_id": board_id,
            "pod_id": pod_id,
            "title": title,
            "mission_dir": os.path.abspath(mission_dir),
            "updated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
        missions_map[link_key] = entry
        cfg["missions"] = missions_map
        save_config_json(settings["config_file"], cfg)

    # Saved before the uploads so a retry after an upload failure reuses this mission and plan.
    save_link()

    uploaded_files = []
    unchanged_files = []
    replaced_ids = []
    if files_to_upload and not args.skip_reports:
        aws_creds = resolve_aws_credentials(settings["creds"])
        timestamp_ms = int(time.time() * 1000)
        reports_input = []

        hashes = {}
        for f in files_to_upload:
            with open(f["path"], "rb") as fh:
                hashes[f["fileName"]] = hashlib.sha256(fh.read()).hexdigest()
        existing_files = []
        if not created_new_mission:
            try:
                existing_files = list_mission_files(settings, pod_id_token, board_id, mission_id, opener=opener)
            except RuntimeError as exc:
                warn("could not list the mission's current files, uploading all: %s" % exc)
        to_upload, unchanged_files, to_delete = plan_file_sync(
            files_to_upload, existing_files, mission_id, hashes, replace=not args.keep_old
        )
        for f in unchanged_files:
            info("Unchanged, skipped: %s" % f["fileName"])

        for item_idx, f in enumerate(to_upload):
            s3_key = "%s/%s/missions/%s/%d-%s" % (
                settings["s3_prefix"],
                board_id,
                mission_id,
                timestamp_ms + item_idx,
                f["fileName"],
            )
            if args.skip_s3:
                host = "%s.s3.%s.amazonaws.com" % (settings["s3_bucket"], settings["s3_region"])
                s3_meta = {
                    "bucket": settings["s3_bucket"],
                    "key": s3_key,
                    "size": f["fileSize"],
                    "region": settings["s3_region"],
                    "s3_uri": "s3://%s/%s" % (settings["s3_bucket"], s3_key),
                    "url": "https://%s/%s" % (host, s3_key),
                }
            else:
                with open(f["path"], "rb") as fh:
                    body_bytes = fh.read()
                if not aws_creds and settings.get("edge_proxy"):
                    # Presigned upload through the edge proxy into the pod's own bucket, as the mobile app does.
                    if not pod_bucket:
                        main_token = ensure_main_token(settings, interactive=interactive, opener=opener)
                        for p in fetch_my_pods(settings, main_token, opener=opener):
                            if p.get("podId") == pod_id:
                                pod_bucket = p.get("bucketName") or ""
                    if not pod_bucket:
                        fail("cannot upload %s: pod %s has no storage bucket" % (f["fileName"], pod_id))
                    try:
                        s3_meta = upload_bytes_via_edge(
                            settings, pod_bucket, s3_key, body_bytes, f["fileType"], opener=opener
                        )
                    except RuntimeError as exc:
                        fail("failed to upload mission file: %s" % exc)
                    info("Uploaded %s -> %s" % (f["fileName"], s3_meta["s3_uri"]))
                elif not aws_creds:
                    # Direct mode without AWS keys: upload through the pod web app instead.
                    if not pod_hostname:
                        main_token = ensure_main_token(settings, interactive=interactive, opener=opener)
                        for p in fetch_my_pods(settings, main_token, opener=opener):
                            if p.get("podId") == pod_id:
                                pod_hostname = p.get("hostname") or ""
                    if not pod_hostname:
                        fail("cannot upload %s: pod %s has no hostname" % (f["fileName"], pod_id))
                    try:
                        s3_meta = upload_bytes_via_pod(
                            pod_hostname, pod_id, board_id, f["fileName"], body_bytes, f["fileType"], opener=opener
                        )
                    except RuntimeError as exc:
                        fail("failed to upload mission file: %s" % exc)
                    info("Uploaded %s -> %s" % (f["fileName"], s3_meta["s3_uri"]))
                else:
                    s3_meta = upload_bytes_to_s3(
                        settings["s3_bucket"],
                        settings["s3_region"],
                        s3_key,
                        body_bytes,
                        f["fileType"],
                        aws_creds,
                        metadata={"missionid": mission_id, "boardid": board_id},
                        opener=opener,
                    )
                    info("Uploaded %s -> %s" % (f["fileName"], s3_meta["s3_uri"]))

            reports_input.append({
                "fileName": f["fileName"],
                "fileType": f["fileType"],
                "fileSize": f["fileSize"],
                "url": s3_meta["url"],
                "s3Object": {
                    "bucket": s3_meta["bucket"],
                    "key": s3_meta["key"],
                    "size": s3_meta["size"],
                    "region": s3_meta["region"],
                    "s3_uri": s3_meta["s3_uri"],
                },
                "note": f["note"],
                "tags": f["tags"] + [mission_id, CLI_FILE_TAG, "sha256:%s" % hashes[f["fileName"]]],
            })

        submit_input = {
            "missionId": mission_id,
            "boardId": board_id,
            "reports": reports_input,
        }
        if plan_id:
            submit_input["planId"] = plan_id

        # Nothing changed means no upload and no registration, but stale copies are still cleaned up.
        registered_on_mission = not reports_input
        if reports_input:
            try:
                rep_data = graphql_request(
                    settings["endpoint"],
                    settings["api_key"],
                    MUTATION_SUBMIT_REPORTS,
                    {"input": submit_input},
                    bearer_token=pod_id_token,
                    opener=opener,
                )
                rep_res = rep_data.get("assistprofile_submitReports") or {}
                if rep_res.get("success"):
                    uploaded_files = rep_res.get("files") or []
                    registered_on_mission = True
                    info(
                        "Registered %d mission report/brief/plan file(s) via assistprofile_submitReports (totalFiles: %s)."
                        % (len(uploaded_files), rep_res.get("totalFiles"))
                    )
                else:
                    raise RuntimeError(rep_res.get("message") or "submitReports returned success=false")
            except RuntimeError as exc:
                if "Mission folder not found" in str(exc) or "missionFolderId" in str(exc):
                    warn("mission has no missionFolderId; falling back to filemanager_createFolder + filemanager_createFile")
                    uploaded_files = fallback_upload_via_filemanager(
                        settings, pod_id_token, board_id, mission_id, title, reports_input, opener=opener
                    )
                    info("Registered %d file(s) in Board File Manager." % len(uploaded_files))
                else:
                    fail("failed to submit mission reports: %s" % exc)

        # Old versions are removed only after the new ones are registered, so a failure never loses a file.
        if registered_on_mission:
            for file_id in to_delete:
                try:
                    data = graphql_request(
                        settings["endpoint"], settings["api_key"], MUTATION_DELETE_MISSION_FILE,
                        {"missionId": mission_id, "boardId": board_id, "fileId": file_id},
                        bearer_token=pod_id_token, opener=opener,
                    )
                    if data.get("assistprofile_deleteMissionFile"):
                        replaced_ids.append(file_id)
                    else:
                        warn("could not remove the previous version (file %s)" % file_id)
                except RuntimeError as exc:
                    warn("could not remove the previous version (file %s): %s" % (file_id, exc))
            if replaced_ids:
                info("Removed %d previous version(s) uploaded by this CLI." % len(replaced_ids))

    target_status = args.status
    if not target_status and os.path.exists(os.path.join(mission_dir, "mission-report.md")):
        target_status = "COMPLETED"
    if target_status:
        try:
            graphql_request(
                settings["endpoint"],
                settings["api_key"],
                MUTATION_UPDATE_MISSION_STATUS,
                {"input": {"boardId": board_id, "missionId": mission_id, "status": target_status}},
                bearer_token=pod_id_token,
                opener=opener,
            )
            info("Updated mission status to %s." % target_status)
        except Exception as exc:
            warn("could not update mission status to %s: %s" % (target_status, exc))

    save_link()

    result_summary = {
        "success": True,
        "pod_id": pod_id,
        "pod_name": pod.get("podName") or "",
        "board_id": board_id,
        "board_name": board.get("name") or "",
        "mission_id": mission_id,
        "created_new_mission": created_new_mission,
        "plan_id": plan_id or "",
        "files_submitted": [f.get("fileName") for f in uploaded_files],
        "files_unchanged": [f["fileName"] for f in unchanged_files],
        "previous_versions_removed": len(replaced_ids),
    }
    if getattr(args, "json", False):
        info(json.dumps(result_summary, indent=2))
    else:
        info("\n=== Mission Submission Summary ===")
        info("  Pod          : %s (%s)" % (result_summary["pod_name"] or pod_id, pod_id))
        info("  Board        : %s (%s)" % (result_summary["board_name"] or board_id, board_id))
        info("  Mission ID   : %s (%s)" % (mission_id, title))
        info("  Plan ID      : %s" % (plan_id or "none"))
        info("  Files        : %s" % (", ".join(result_summary["files_submitted"]) or "none"))
        if unchanged_files:
            info("  Unchanged    : %s" % ", ".join(result_summary["files_unchanged"]))
    return 0


def cmd_progress(args, opener=None):
    """Post a live status change and/or a progress comment to a mission already linked to a board."""
    from .operations import MUTATION_CREATE_MISSION_COMMENT
    from .operations import MUTATION_UPDATE_MISSION_STATUS
    from .common import fail
    from .api import graphql_request
    from .common import info
    from .documents import parse_mission_metadata
    from .auth import resolve_settings
    if not args.status and not args.comment:
        fail("pass --status, --comment, or both")
    settings = resolve_settings(args.credentials_file, args.config, args)
    interactive = not getattr(args, "no_input", False) and sys.stdin.isatty()
    cfg = settings["cfg"]
    missions_map = cfg.get("missions") if isinstance(cfg.get("missions"), dict) else {}

    entry = {}
    if args.mission_dir:
        if not os.path.isdir(args.mission_dir):
            fail("--mission-dir %s does not exist or is not a directory" % args.mission_dir)
        _key, entry = find_linked_mission(missions_map, args.mission_dir, parse_mission_metadata(args.mission_dir)["slug"])
    mission_id = args.mission_id or entry.get("mission_id")
    board_id = args.board or entry.get("board_id") or cfg.get("board_id")
    if not mission_id:
        fail("this mission is not on a board yet. Run `submit --mission-dir <dir>` first, or pass --mission-id.")
    if not board_id:
        fail("no board selected. Pass --board <boardId> or run `select`.")

    _pod, pod_id_token, _profile = _resolve_pod_token_and_profile(
        settings, pod_arg=args.pod or entry.get("pod_id"), interactive=interactive, opener=opener
    )
    result = {"mission_id": mission_id, "board_id": board_id, "status": "", "comment_id": ""}
    if args.status:
        graphql_request(
            settings["endpoint"], settings["api_key"], MUTATION_UPDATE_MISSION_STATUS,
            {"input": {"boardId": board_id, "missionId": mission_id, "status": args.status}},
            bearer_token=pod_id_token, opener=opener,
        )
        result["status"] = args.status
    if args.comment:
        data = graphql_request(
            settings["endpoint"], settings["api_key"], MUTATION_CREATE_MISSION_COMMENT,
            {"input": {"missionId": mission_id, "boardId": board_id, "text": args.comment}},
            bearer_token=pod_id_token, opener=opener,
        )
        result["comment_id"] = (data.get("assistprofile_createMissionComment") or {}).get("commentId") or ""
    if getattr(args, "json", False):
        info(json.dumps(result, indent=2))
    else:
        if result["status"]:
            info("Mission %s status: %s" % (mission_id, result["status"]))
        if args.comment:
            info("Posted progress comment on mission %s." % mission_id)
    return 0


def _add_common_flags(parser, is_subparser=False):
    sup = argparse.SUPPRESS if is_subparser else None
    cfg_default = argparse.SUPPRESS if is_subparser else ".actionboard/config.json"
    parser.add_argument("--credentials-file", default=sup, help="path to credentials.json (default: ~/.actionboard/credentials.json)")
    parser.add_argument("--config", default=cfg_default, help="project config path (default: .actionboard/config.json)")
    parser.add_argument("--endpoint", default=sup, help="override AppSync GraphQL endpoint URL")
    parser.add_argument("--api-key", default=sup, help="override AppSync API key")
    parser.add_argument("--s3-region", default=sup, help="override S3 region (default: ap-southeast-1)")
    parser.add_argument("--s3-bucket", default=sup, help="override S3 bucket (default: actionboard-kb-agent)")
    parser.add_argument("--s3-prefix", default=sup, help="override S3 key prefix (default: PremiumBoardKB/Boards/Investor+Boards)")


def build_parser():
    from .operations import SYNC_MODES
    p = argparse.ArgumentParser(
        prog="submit_mission.py",
        description="Submit ActionBoard mission brief, plan, and report from the CLI.",
    )
    _add_common_flags(p, is_subparser=False)

    common_sub = argparse.ArgumentParser(add_help=False)
    _add_common_flags(common_sub, is_subparser=True)

    sub = p.add_subparsers(dest="subcommand", required=True)

    sp_cfg = sub.add_parser("configure", parents=[common_sub], help="save AppSync and S3 settings to ~/.actionboard/credentials.json")
    sp_cfg.add_argument("--from-env-file", help="import settings from an env/markdown file")
    sp_cfg.add_argument("--edge-proxy-url", help="route all calls through this edge proxy (no API key needed); pass \"\" to go back to direct mode")
    sp_cfg.add_argument("--cognito-domain", help="Cognito domain URL")
    sp_cfg.add_argument("--cognito-client-id", help="Cognito client ID")
    sp_cfg.add_argument("--aws-access-key-id", help="AWS access key ID for S3 upload")
    sp_cfg.add_argument("--aws-secret-access-key", help="AWS secret access key for S3 upload")
    sp_cfg.add_argument("--aws-session-token", help="AWS session token (optional)")

    sp_login = sub.add_parser("login", parents=[common_sub], help="authenticate with ActionBoard and cache tokens")
    sp_login.add_argument("--email", help="ActionBoard account email")
    sp_login.add_argument("--password", help="sign in with a password instead of the browser (prefer ACTIONBOARD_PASSWORD; flags show in shell history)")
    sp_login.add_argument("--browser", action="store_true", help="sign in through the browser (the default unless a password is given)")
    sp_login.add_argument("--provider", choices=["Google", "LinkedIn", "GitHub"], help="go straight to this sign-in provider in the browser")
    sp_login.add_argument("--no-browser", action="store_true", help="print the sign-in link instead of opening a browser")
    sp_login.add_argument("--timeout", type=int, default=300, help="seconds to wait for the browser sign-in (default: 300)")

    sub.add_parser("logout", parents=[common_sub], help="remove stored tokens from the keychain and credentials file")

    sp_status = sub.add_parser("status", parents=[common_sub], help="show current auth, S3, and Pod/Board selection status")
    sp_status.add_argument("--json", action="store_true", help="output JSON")

    sp_pods = sub.add_parser("pods", parents=[common_sub], help="list pods the authenticated user belongs to")
    sp_pods.add_argument("--no-input", action="store_true", help="do not prompt interactively")
    sp_pods.add_argument("--json", action="store_true", help="output JSON")

    sp_boards = sub.add_parser("boards", parents=[common_sub], help="list boards in a pod")
    sp_boards.add_argument("--pod", help="pod ID, slug, or name")
    sp_boards.add_argument("--search", help="filter boards by search term")
    sp_boards.add_argument("--no-input", action="store_true", help="do not prompt interactively")
    sp_boards.add_argument("--json", action="store_true", help="output JSON")

    sp_missions = sub.add_parser("missions", parents=[common_sub], help="list or delete missions on a board")
    sp_missions.add_argument("--pod", help="pod ID")
    sp_missions.add_argument("--board", help="board ID")
    sp_missions.add_argument("--delete", metavar="MISSION_ID", help="delete a mission by ID")
    sp_missions.add_argument("--no-input", action="store_true", help="do not prompt interactively")
    sp_missions.add_argument("--json", action="store_true", help="output JSON")

    sp_assigned = sub.add_parser("assigned", parents=[common_sub], help="list missions and invitations assigned to you")
    sp_assigned.add_argument("--pod", help="pod ID, slug, or name")
    sp_assigned.add_argument("--board", help="filter by board ID")
    sp_assigned.add_argument("--invitation-status", choices=["PENDING", "ACCEPTED", "DECLINED", "EXPIRED"],
                             help="filter invitations by status")
    sp_assigned.add_argument("--no-input", action="store_true", help="do not prompt interactively")
    sp_assigned.add_argument("--json", action="store_true", help="output JSON")

    sp_fetch = sub.add_parser("fetch", parents=[common_sub], help="fetch an assigned mission's brief and plan to start work")
    sp_fetch.add_argument("--pod", help="pod ID, slug, or name")
    sp_fetch.add_argument("--board", help="board ID")
    sp_fetch.add_argument("--mission-id", help="missionId to fetch (auto-selects assigned mission if omitted)")
    sp_fetch.add_argument("--invitation-id", help="invitationId to fetch")
    sp_fetch.add_argument("--plan-id", help="specific planId to fetch")
    sp_fetch.add_argument("--out-dir", help="local directory to write mission-brief.md and mission-plan.md")
    sp_fetch.add_argument("--accept", action="store_true", help="accept a PENDING mission invitation when fetching")
    sp_fetch.add_argument("--start", action="store_true", help="update mission status to IN_PROGRESS after fetching")
    sp_fetch.add_argument("--no-input", action="store_true", help="fail or auto-pick first assigned mission instead of prompting")
    sp_fetch.add_argument("--json", action="store_true", help="output JSON summary")

    sp_select = sub.add_parser("select", parents=[common_sub], help="interactively select default Pod and Board for this project")
    sp_select.add_argument("--pod", help="pod ID, slug, or name")
    sp_select.add_argument("--board", help="board ID or name")
    sp_select.add_argument("--sync", choices=SYNC_MODES,
                           help="mission board sync: ask (default) asks once per mission, auto syncs without asking, off never syncs")

    sp_progress = sub.add_parser("progress", parents=[common_sub], help="post a status change or progress comment to a linked mission")
    sp_progress.add_argument("--mission-dir", help="local mission folder that was submitted or fetched before")
    sp_progress.add_argument("--mission-id", help="missionId (instead of --mission-dir)")
    sp_progress.add_argument("--pod", help="pod ID")
    sp_progress.add_argument("--board", help="board ID")
    sp_progress.add_argument("--status", choices=["INITIATED", "IN_PROGRESS", "COMPLETED", "FAILED", "ARCHIVED"],
                             help="new mission status")
    sp_progress.add_argument("--comment", help="progress comment text to post on the mission")
    sp_progress.add_argument("--no-input", action="store_true", help="do not prompt interactively")
    sp_progress.add_argument("--json", action="store_true", help="output JSON")

    sp_submit = sub.add_parser("submit", parents=[common_sub], help="submit mission brief, plan, and report to a board")
    sp_submit.add_argument("--mission-dir", help="path to mission folder (auto-detected if omitted)")
    sp_submit.add_argument("--pod", help="target pod ID, slug, or name")
    sp_submit.add_argument("--board", help="target board ID or name")
    sp_submit.add_argument("--mission-id", help="existing missionId on the board (creates or matches by title if omitted)")
    sp_submit.add_argument("--plan-id", help="existing planId to update")
    sp_submit.add_argument("--invitation-id", help="submit against a mission invitationId")
    sp_submit.add_argument("--assigned-agent", help="assignedAgentProfileId (defaults to logged-in user's profileId)")
    sp_submit.add_argument("--title", help="override mission title")
    sp_submit.add_argument("--description", help="override mission shortDescription")
    sp_submit.add_argument("--status", choices=["INITIATED", "IN_PROGRESS", "COMPLETED", "FAILED", "ARCHIVED"],
                           help="explicit mission status to set")
    sp_submit.add_argument("--create-mission", action="store_true", help="always create a new mission on the board")
    sp_submit.add_argument("--update-mission", action="store_true", help="update existing mission title/shortDescription")
    sp_submit.add_argument("--skip-plan", action="store_true", help="skip submitting mission plan markdown")
    sp_submit.add_argument("--skip-reports", action="store_true", help="skip uploading mission report files")
    sp_submit.add_argument("--skip-s3", action="store_true", help="register report metadata in AppSync without S3 PUT")
    sp_submit.add_argument("--keep-old", action="store_true",
                           help="keep previous versions of changed files instead of replacing them")
    sp_submit.add_argument("--dry-run", action="store_true", help="validate local files and print what would be submitted")
    sp_submit.add_argument("--no-input", action="store_true", help="fail instead of prompting interactively")
    sp_submit.add_argument("--json", action="store_true", help="output JSON summary")

    return p


def main(argv=None, opener=None):
    from .common import fail
    parser = build_parser()
    args = parser.parse_args(argv)
    dispatch = {
        "configure": lambda: cmd_configure(args),
        "login": lambda: cmd_login(args, opener=opener),
        "logout": lambda: cmd_logout(args),
        "status": lambda: cmd_status(args),
        "pods": lambda: cmd_pods(args, opener=opener),
        "boards": lambda: cmd_boards(args, opener=opener),
        "missions": lambda: cmd_missions(args, opener=opener),
        "assigned": lambda: cmd_assigned(args, opener=opener),
        "fetch": lambda: cmd_fetch(args, opener=opener),
        "select": lambda: cmd_select(args, opener=opener),
        "submit": lambda: cmd_submit(args, opener=opener),
        "progress": lambda: cmd_progress(args, opener=opener),
    }
    try:
        return dispatch[args.subcommand]()
    except RuntimeError as exc:
        # AppSync GraphQL errors: report the server's message instead of a traceback.
        fail("%s failed: %s" % (args.subcommand, exc))


