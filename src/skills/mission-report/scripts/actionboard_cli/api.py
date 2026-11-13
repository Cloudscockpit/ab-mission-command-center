"""ActionBoard CLI: api."""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

def _edge_auth_token(bearer_token, opener=None):
    """The edge proxy only accepts main-pool tokens in X-Edge-Auth; pod tokens ride in Authorization."""
    from .common import _EDGE_CONTEXT
    from .auth import ensure_main_token
    settings = _EDGE_CONTEXT.get("settings")
    if not bearer_token or not settings:
        return bearer_token
    pod_tokens = {
        (t or {}).get("id_token")
        for t in ((settings.get("creds") or {}).get("pod_tokens") or {}).values()
    }
    pod_tokens.add(os.environ.get("ACTIONBOARD_POD_ID_TOKEN"))
    if bearer_token in pod_tokens:
        return ensure_main_token(settings, interactive=False, opener=opener)
    return bearer_token


def edge_http(settings, path, payload, opener=None, timeout=60):
    """POST JSON to an edge proxy route with the main-pool token."""
    from .auth import ensure_main_token
    main_token = ensure_main_token(settings, interactive=False, opener=opener)
    req = urllib.request.Request(
        settings["edge_proxy"] + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "ActionBoard-CLI/1.2",
            "X-Edge-Auth": "Bearer %s" % main_token,
            "Authorization": "Bearer %s" % main_token,
        },
        method="POST",
    )
    open_fn = opener or urllib.request.urlopen
    try:
        with open_fn(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        raise RuntimeError("edge proxy %s HTTP %s: %s" % (path, exc.code, body[:300] or exc.reason))
    except (urllib.error.URLError, OSError) as exc:
        raise RuntimeError("edge proxy %s network error: %s" % (path, getattr(exc, "reason", exc)))
    try:
        return json.loads(raw)
    except ValueError:
        raise RuntimeError("edge proxy %s returned non-JSON: %s" % (path, raw[:200]))


def edge_presign(settings, bucket, key, method, opener=None, expires_in=900):
    res = edge_http(settings, "/s3/sign", {"bucket": bucket, "key": key, "method": method, "expiresIn": expires_in}, opener=opener)
    if not isinstance(res, dict) or not res.get("url"):
        raise RuntimeError("edge proxy returned no signed URL for %s" % key)
    return res["url"], res.get("region") or settings["s3_region"]


def upload_bytes_via_edge(settings, bucket, key, body_bytes, content_type, opener=None):
    url, region = edge_presign(settings, bucket, key, "PUT", opener=opener)
    req = urllib.request.Request(url, data=body_bytes, headers={"Content-Type": content_type}, method="PUT")
    open_fn = opener or urllib.request.urlopen
    try:
        with open_fn(req, timeout=90) as resp:
            resp.read()
    except urllib.error.HTTPError as exc:
        raise RuntimeError("S3 PUT HTTP %s for %s" % (exc.code, key))
    except (urllib.error.URLError, OSError) as exc:
        raise RuntimeError("S3 PUT network error for %s: %s" % (key, getattr(exc, "reason", exc)))
    return {
        "bucket": bucket,
        "key": key,
        "size": len(body_bytes),
        "region": region,
        "s3_uri": "s3://%s/%s" % (bucket, key),
        "url": "https://%s.s3.%s.amazonaws.com/%s" % (bucket, region, key),
    }


def download_bytes_via_edge(settings, bucket, key, opener=None):
    url, _region = edge_presign(settings, bucket, key, "GET", opener=opener)
    req = urllib.request.Request(url, method="GET")
    open_fn = opener or urllib.request.urlopen
    try:
        with open_fn(req, timeout=60) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        raise RuntimeError("S3 GET HTTP %s for %s" % (exc.code, key))
    except (urllib.error.URLError, OSError) as exc:
        raise RuntimeError("S3 GET network error for %s: %s" % (key, getattr(exc, "reason", exc)))


def graphql_request(endpoint, api_key, query, variables=None, bearer_token=None, opener=None):
    from .common import fail
    if not endpoint:
        fail(
            "AppSync endpoint is not configured. Run `python submit_mission.py configure "
            "--endpoint <url> --api-key <key>` or set APPSYNC_GRAPHQL_ENDPOINT."
        )
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "ActionBoard-CLI/1.2",
    }
    if api_key:
        headers["x-api-key"] = api_key
    if bearer_token:
        headers["Authorization"] = "Bearer %s" % bearer_token
        if not api_key:
            headers["X-Edge-Auth"] = "Bearer %s" % _edge_auth_token(bearer_token, opener=opener)

    payload = {"query": query, "variables": variables or {}}
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
    open_fn = opener or urllib.request.urlopen

    try:
        with open_fn(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        err_body = ""
        try:
            err_body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        fail("AppSync HTTP %s: %s" % (exc.code, err_body or exc.reason))
    except urllib.error.URLError as exc:
        fail("network error contacting AppSync (%s): %s" % (endpoint, exc.reason))
    except OSError as exc:
        # socket.timeout while reading the response is not a URLError.
        fail("network error contacting AppSync (%s): %s. Retry the command." % (endpoint, exc))

    try:
        parsed = json.loads(raw)
    except ValueError:
        fail("AppSync returned non-JSON response: %s" % raw[:200])

    if parsed.get("errors"):
        messages = "; ".join(
            str(e.get("message") or e) for e in parsed["errors"] if isinstance(e, dict)
        )
        raise RuntimeError(messages or json.dumps(parsed["errors"]))

    return parsed.get("data") or {}


def fetch_my_boards(settings, pod_id_token, pod_id=None, search_term=None, opener=None):
    from .operations import QUERY_MY_BOARDS
    from .operations import QUERY_MY_BOARDS_SEARCH
    from .common import fail
    variables = {}
    if pod_id:
        variables["podId"] = pod_id
    if search_term:
        variables["searchTerm"] = search_term
        query = QUERY_MY_BOARDS_SEARCH
    else:
        query = QUERY_MY_BOARDS
    data = graphql_request(
        settings["endpoint"],
        settings["api_key"],
        query,
        variables,
        bearer_token=pod_id_token,
        opener=opener,
    )
    res = data.get("boards_getMyBoards") or {}
    if not res.get("success"):
        fail("failed to fetch boards: %s" % (res.get("message") or "unknown error"))
    return res.get("data") or []


def fetch_missions_by_board(settings, pod_id_token, board_id, limit=25, opener=None):
    from .operations import QUERY_LIST_MISSIONS_BY_BOARD
    data = graphql_request(
        settings["endpoint"],
        settings["api_key"],
        QUERY_LIST_MISSIONS_BY_BOARD,
        {"boardId": board_id, "limit": limit},
        bearer_token=pod_id_token,
        opener=opener,
    )
    conn = data.get("assistprofile_listMissionsByBoard") or {}
    return conn.get("items") or []


def fetch_missions_by_agent(settings, pod_id_token, agent_profile_id, limit=25, opener=None):
    from .operations import QUERY_LIST_MISSIONS_BY_AGENT
    if not agent_profile_id:
        return []
    data = graphql_request(
        settings["endpoint"],
        settings["api_key"],
        QUERY_LIST_MISSIONS_BY_AGENT,
        {"actionAssistAgentId": agent_profile_id, "limit": limit},
        bearer_token=pod_id_token,
        opener=opener,
    )
    conn = data.get("assistprofile_listMissionsByAgent") or {}
    return conn.get("items") or []


def fetch_my_invitations(settings, pod_id_token, status=None, limit=25, opener=None):
    from .operations import QUERY_GET_MY_MISSION_INVITATIONS
    from .operations import QUERY_GET_MY_MISSION_INVITATIONS_BY_STATUS
    variables = {"limit": limit}
    if status:
        variables["status"] = status
        query = QUERY_GET_MY_MISSION_INVITATIONS_BY_STATUS
    else:
        query = QUERY_GET_MY_MISSION_INVITATIONS
    data = graphql_request(
        settings["endpoint"],
        settings["api_key"],
        query,
        variables,
        bearer_token=pod_id_token,
        opener=opener,
    )
    conn = data.get("assistprofile_getMyMissionInvitations") or {}
    return conn.get("items") or []


def fetch_mission(settings, pod_id_token, board_id, mission_id, opener=None):
    from .operations import QUERY_GET_MISSION
    data = graphql_request(
        settings["endpoint"],
        settings["api_key"],
        QUERY_GET_MISSION,
        {"boardId": board_id, "missionId": mission_id},
        bearer_token=pod_id_token,
        opener=opener,
    )
    return data.get("assistprofile_getMission")


def fetch_mission_plans(settings, pod_id_token, mission_id, limit=20, opener=None):
    from .operations import QUERY_LIST_MISSION_PLANS_BY_MISSION
    data = graphql_request(
        settings["endpoint"],
        settings["api_key"],
        QUERY_LIST_MISSION_PLANS_BY_MISSION,
        {"missionId": mission_id, "limit": limit},
        bearer_token=pod_id_token,
        opener=opener,
    )
    conn = data.get("assistprofile_listMissionPlansByMission") or {}
    return conn.get("items") or []


def fetch_files_by_board_and_folder(settings, pod_id_token, board_id, folder_id, limit=50, opener=None):
    from .operations import QUERY_FILES_BY_BOARD_AND_FOLDER
    if not board_id or not folder_id:
        return []
    try:
        data = graphql_request(
            settings["endpoint"],
            settings["api_key"],
            QUERY_FILES_BY_BOARD_AND_FOLDER,
            {"boardId": board_id, "folderId": folder_id, "limit": limit},
            bearer_token=pod_id_token,
            opener=opener,
        )
        res = data.get("filemanager_filesByBoardAndFolder") or {}
        conn = res.get("data") or {}
        return conn.get("items") or []
    except Exception:
        return []


