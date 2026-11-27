"""ActionBoard CLI: pod service wrappers (ActionLists, action items, Goals, Files).

Every function takes `settings` (from auth.resolve_settings, which also registers the
edge-proxy context) and `pod_token` (the pod ID token from commands._resolve_pod_token_and_profile)
as its first two arguments, and accepts `opener=None` as a keyword so tests can mock transport
(the same seam api.graphql_request uses). Each wrapper unwraps the `{success, message, data}`
envelope and raises RuntimeError(<server message>) when success is false or data is missing.
Error text is scrubbed of bearer tokens, JWTs, and URL query strings (presigned signatures).

Field dicts use the live schema field names exactly (for example "action", "actionListStatus",
"Tags", "ActionItem", "ActionStatus", "Notes"). None values are dropped, so only what the caller
set is sent. Unknown keys raise ValueError. Enum values are validated against the tuples below.

Exported enum tuples (use as argparse `choices`):
  ACTIONLIST_STATUSES   Actionlists_Status for actionListStatus / ActionStatus
  GOAL_STATUSES         Actiongoals_ActionGoalStatus
  GOAL_PRIORITIES       Actiongoals_ActionGoalPriority

ActionLists (record = dict with id, boardId, action, actionListStatus, notes, Tags, dueDate,
startDate, isImportant, isUrgent, orderRank, _version, createdAt, updatedAt, ...)
  create_actionlist(settings, pod_token, board_id, fields, opener=None) -> record
      fields must include "action".
  list_actionlists(settings, pod_token, board_id, status=None, limit=50, next_token=None,
                   opener=None) -> {"items": [record], "nextToken": str|None, "totalCount": int|None}
  find_actionlist(settings, pod_token, board_id, list_id, page_size=100, max_pages=20,
                  opener=None) -> record or None   (no single-get exists; pages the list)
  update_actionlist(settings, pod_token, board_id, list_id, fields, version=None, opener=None)
      -> record. Reads the current record (RuntimeError if not found) and sends its _version
      unless `version` is given.
  delete_actionlist(settings, pod_token, board_id, list_id, version=None, opener=None)
      -> record (id, boardId, action, _version, _deleted). Sends the current _version.

Action items (record = dict with id, actionlistID, ActionItem, ActionStatus, Notes, tags,
dueDate, _version, ...)
  create_action(settings, pod_token, board_id, actionlist_id, fields, opener=None) -> record
  get_action(settings, pod_token, action_id, opener=None) -> record (RuntimeError if missing)
  list_actions(settings, pod_token, actionlist_id, statuses=None, limit=50, next_token=None,
               opener=None) -> {"items": [...], "nextToken": ..., "totalCount": ...}
  update_action(settings, pod_token, board_id, action_id, fields, version=None, opener=None)
      -> record. Reads the action (for actionlistID and _version); `version` overrides _version.
  delete_action(settings, pod_token, board_id, action_id, opener=None) -> record
      (id, actionlistID, ActionItem, _version, _deleted). Reads the action for actionlistID.

Goals (record = dict with id, title, description, priority, status, assignedUserId, dueDate,
startDate, boardId, userId, profileId, createdAt, updatedAt; the type has NO _version)
  create_goal(settings, pod_token, board_id, title, priority, fields=None, user_id=None,
              opener=None) -> record. userId comes from `user_id`, else current_user_id().
  get_goal(settings, pod_token, board_id, goal_id, opener=None) -> record
  list_goals(settings, pod_token, board_id, limit=50, next_token=None, opener=None)
      -> {"items": [...], "nextToken": ...}
  update_goal(settings, pod_token, board_id, goal_id, fields, opener=None) -> record
  delete_goal(settings, pod_token, board_id, goal_id, opener=None) -> record (id, boardId, title)
  current_user_id(settings, pod_token) -> str   (identity source documented below)

Files
  list_folders(settings, pod_token, board_id, limit=100, opener=None) -> [folder dict]
      (id, boardId, folderName, parentFolderId)
  create_folder(settings, pod_token, board_id, name, parent_folder_id=None, opener=None)
      -> folder dict
  list_files(settings, pod_token, board_id, folder_id, limit=50, opener=None) -> [file record]
  get_file(settings, pod_token, file_id, opener=None) -> file record (RuntimeError if missing)
  delete_file(settings, pod_token, file_id, opener=None) -> {id, boardId, folderId, fileName}
  upload_file(settings, pod_token, pod_id, board_id, folder_id, path, note=None, tags=None,
              bucket=None, region=None, opener=None) -> file record created in File Manager.
      Presigns through the edge proxy, PUTs to the pod bucket, then registers with
      filemanager_createFile (s3Object {bucket,key,size,region,s3_uri}, url).
  download_file(settings, pod_token, file_id, out_dir, overwrite=False, opener=None)
      -> {"path": absolute path written, "fileName": server name, "size": bytes, "id": file_id}.
      Writes only a sanitized basename inside out_dir (absolute or ".." names rejected, symlink targets refused); FileExistsError if the file exists
      and overwrite is False; ValueError for unsafe names.
  safe_basename(name) -> str   (raises ValueError for empty, ".", "..", or separator-only names)

Identity for goal userId: the `sub` claim of the pod ID token. Verified live: existing goals
created by the signed-in profile carry userId equal to the pod token `sub`, and it differs from
settings["creds"]["user_id"] (the main-pool userId) and from custom:mainCognitoSub. Falls back to
creds["user_id"] only when the pod token has no `sub`.

Not idempotent: create_* and upload_file create a new record on every call.
"""
import json
import mimetypes
import os
import re
import tempfile
import time
import urllib.error
import urllib.request

ACTIONLIST_STATUSES = (
    "New", "Todo", "Active", "In_Progress", "Done", "AutoActionAiAgent", "ActionAssistAgent",
)
GOAL_STATUSES = ("PENDING", "IN_PROGRESS", "COMPLETED")
GOAL_PRIORITIES = ("LOW", "MEDIUM", "HIGH")

_ACTIONLIST_KEYS = (
    "action", "actionListStatus", "orderRank", "knowledgeBaseID", "savedBy", "Tags", "Context",
    "notes", "isImportant", "isUrgent", "Delegate", "Ignore", "dueDate", "startDate",
)
_ACTION_KEYS = (
    "ActionItem", "ActionStatus", "actionListStatus", "prompt", "Type", "Owner", "Notify",
    "orderRank", "knowledgeBaseID", "tags", "isImportant", "isUrgent", "Accepted", "Delegate",
    "Ignore", "Encrypt", "dueDate", "startDate", "Notes", "FileUrls", "KBLink", "GuardRails",
    "History", "userLike", "impactScore",
)
_GOAL_KEYS = (
    "description", "status", "assignedUserId", "dueDate", "startDate", "title", "priority",
)
_STATUS_KEYS = ("actionListStatus", "ActionStatus")

_TOKEN_RE = re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+")
_JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]*")
_URL_QS_RE = re.compile(r"(https?://[^\s\"'<>?]+)\?[^\s\"'<>]*")


def _scrub(text):
    """Remove tokens and URL query strings (presigned signatures) from text."""
    text = str(text)
    text = _TOKEN_RE.sub("Bearer [redacted]", text)
    text = _JWT_RE.sub("[redacted-token]", text)
    text = _URL_QS_RE.sub(r"\1?[redacted]", text)
    return text


def _compact(fields, allowed, enum_checks=True):
    """Drop None values, reject unknown keys, validate enums."""
    out = {}
    for key, value in (fields or {}).items():
        if value is None:
            continue
        if key not in allowed:
            raise ValueError("unsupported field: %s" % key)
        out[key] = value
    for key in _STATUS_KEYS:
        if key in out and out[key] not in ACTIONLIST_STATUSES:
            raise ValueError("%s must be one of: %s" % (key, ", ".join(ACTIONLIST_STATUSES)))
    if "status" in out and out["status"] not in GOAL_STATUSES:
        raise ValueError("status must be one of: %s" % ", ".join(GOAL_STATUSES))
    if "priority" in out and out["priority"] not in GOAL_PRIORITIES:
        raise ValueError("priority must be one of: %s" % ", ".join(GOAL_PRIORITIES))
    return out


def _gql(settings, pod_token, query, variables, root, opener=None, allow_empty=False):
    """Run one operation and return the envelope's data. Raises RuntimeError on failure."""
    from .api import graphql_request
    try:
        data = graphql_request(
            settings["endpoint"], settings.get("api_key"), query, variables,
            bearer_token=pod_token, opener=opener,
        )
    except SystemExit as exc:
        raise RuntimeError("request failed (exit %s); see stderr" % (exc.code,))
    except RuntimeError as exc:
        raise RuntimeError(_scrub(exc))
    res = (data or {}).get(root)
    if not isinstance(res, dict):
        raise RuntimeError("%s returned no result" % root)
    if not res.get("success"):
        raise RuntimeError(_scrub(res.get("message") or "%s failed" % root))
    payload = res.get("data")
    if payload is None and not allow_empty:
        raise RuntimeError(_scrub(res.get("message") or "%s returned no data" % root))
    return payload


def _page(payload):
    payload = payload or {}
    return {
        "items": payload.get("items") or [],
        "nextToken": payload.get("nextToken"),
        "totalCount": payload.get("totalCount"),
    }


# --------------------------------------------------------------------------- ActionLists

def create_actionlist(settings, pod_token, board_id, fields, opener=None):
    from .operations import MUTATION_CREATE_ACTIONLIST
    body = _compact(fields, _ACTIONLIST_KEYS)
    if not body.get("action"):
        raise ValueError("action is required")
    body["boardId"] = board_id
    return _gql(settings, pod_token, MUTATION_CREATE_ACTIONLIST, {"input": body},
                "actionlists_createActionList", opener)


def list_actionlists(settings, pod_token, board_id, status=None, limit=50, next_token=None, opener=None):
    from .operations import QUERY_GET_ALL_ACTIONLISTS
    if status is not None and status not in ACTIONLIST_STATUSES:
        raise ValueError("status must be one of: %s" % ", ".join(ACTIONLIST_STATUSES))
    inp = {"boardId": board_id, "pagination": {"limit": limit}}
    if next_token:
        inp["pagination"]["nextToken"] = next_token
    if status:
        inp["filter"] = {"actionListStatus": status}
    payload = _gql(settings, pod_token, QUERY_GET_ALL_ACTIONLISTS, {"input": inp},
                   "actionlists_getAllActionLists", opener, allow_empty=True)
    return _page(payload)


def find_actionlist(settings, pod_token, board_id, list_id, page_size=100, max_pages=20, opener=None):
    token = None
    for _ in range(max_pages):
        page = list_actionlists(settings, pod_token, board_id, limit=page_size,
                                next_token=token, opener=opener)
        for item in page["items"]:
            if item.get("id") == list_id:
                return item
        token = page["nextToken"]
        if not token:
            return None
    return None


def _require_actionlist(settings, pod_token, board_id, list_id, opener):
    record = find_actionlist(settings, pod_token, board_id, list_id, opener=opener)
    if not record:
        raise RuntimeError("action list %s not found on board %s" % (list_id, board_id))
    return record


def update_actionlist(settings, pod_token, board_id, list_id, fields, version=None, opener=None):
    from .operations import MUTATION_UPDATE_ACTIONLIST
    body = _compact(fields, _ACTIONLIST_KEYS)
    if not body:
        raise ValueError("nothing to update")
    if version is None:
        version = _require_actionlist(settings, pod_token, board_id, list_id, opener).get("_version")
    body.update({"id": list_id, "boardId": board_id})
    if version is not None:
        body["_version"] = version
    return _gql(settings, pod_token, MUTATION_UPDATE_ACTIONLIST, {"input": body},
                "actionlists_updateActionList", opener)


def delete_actionlist(settings, pod_token, board_id, list_id, version=None, opener=None):
    from .operations import MUTATION_DELETE_ACTIONLIST
    if version is None:
        version = _require_actionlist(settings, pod_token, board_id, list_id, opener).get("_version")
    body = {"id": list_id, "boardId": board_id}
    if version is not None:
        body["_version"] = version
    return _gql(settings, pod_token, MUTATION_DELETE_ACTIONLIST, {"input": body},
                "actionlists_deleteActionList", opener)


# --------------------------------------------------------------------------- Action items

def create_action(settings, pod_token, board_id, actionlist_id, fields, opener=None):
    from .operations import MUTATION_CREATE_ACTION
    body = _compact(fields, _ACTION_KEYS)
    if not body.get("ActionItem"):
        raise ValueError("ActionItem is required")
    body.update({"actionlistID": actionlist_id, "boardId": board_id})
    return _gql(settings, pod_token, MUTATION_CREATE_ACTION, {"input": body},
                "actionlists_createAction", opener)


def get_action(settings, pod_token, action_id, opener=None):
    from .operations import QUERY_GET_ACTION
    return _gql(settings, pod_token, QUERY_GET_ACTION, {"id": action_id},
                "actionlists_getAction", opener)


def list_actions(settings, pod_token, actionlist_id, statuses=None, limit=50, next_token=None, opener=None):
    from .operations import QUERY_GET_ALL_ACTIONS
    inp = {"actionlistID": actionlist_id, "pagination": {"limit": limit}}
    if next_token:
        inp["pagination"]["nextToken"] = next_token
    if statuses:
        for s in statuses:
            if s not in ACTIONLIST_STATUSES:
                raise ValueError("status must be one of: %s" % ", ".join(ACTIONLIST_STATUSES))
        inp["filter"] = {"actionStatus": list(statuses)}
    payload = _gql(settings, pod_token, QUERY_GET_ALL_ACTIONS, {"input": inp},
                   "actionlists_getAllActions", opener, allow_empty=True)
    return _page(payload)


def update_action(settings, pod_token, board_id, action_id, fields, version=None, opener=None):
    from .operations import MUTATION_UPDATE_ACTION
    body = _compact(fields, _ACTION_KEYS)
    if not body:
        raise ValueError("nothing to update")
    current = get_action(settings, pod_token, action_id, opener=opener)
    if version is None:
        version = current.get("_version")
    body.update({"id": action_id, "actionlistID": current.get("actionlistID"), "boardId": board_id})
    if version is not None:
        body["_version"] = version
    return _gql(settings, pod_token, MUTATION_UPDATE_ACTION, {"input": body},
                "actionlists_updateAction", opener)


def delete_action(settings, pod_token, board_id, action_id, opener=None):
    from .operations import MUTATION_DELETE_ACTION
    current = get_action(settings, pod_token, action_id, opener=opener)
    body = {"id": action_id, "actionlistID": current.get("actionlistID"), "boardId": board_id}
    return _gql(settings, pod_token, MUTATION_DELETE_ACTION, {"input": body},
                "actionlists_deleteAction", opener)


# --------------------------------------------------------------------------- Goals

def current_user_id(settings, pod_token=None):
    from .auth import decode_jwt_payload
    user_id = decode_jwt_payload(pod_token).get("sub") or (settings.get("creds") or {}).get("user_id")
    if not user_id:
        raise RuntimeError("cannot determine your user id; run the login command first")
    return user_id


def create_goal(settings, pod_token, board_id, title, priority, fields=None, user_id=None, opener=None):
    from .operations import MUTATION_CREATE_ACTION_GOAL
    if not title:
        raise ValueError("title is required")
    body = _compact(fields, _GOAL_KEYS)
    body.pop("title", None)
    body.pop("priority", None)
    if priority not in GOAL_PRIORITIES:
        raise ValueError("priority must be one of: %s" % ", ".join(GOAL_PRIORITIES))
    body.update({
        "title": title,
        "priority": priority,
        "boardId": board_id,
        "userId": user_id or current_user_id(settings, pod_token),
    })
    return _gql(settings, pod_token, MUTATION_CREATE_ACTION_GOAL, {"input": body},
                "actiongoals_createActionGoal", opener)


def get_goal(settings, pod_token, board_id, goal_id, opener=None):
    from .operations import QUERY_GET_ACTION_GOAL
    return _gql(settings, pod_token, QUERY_GET_ACTION_GOAL, {"id": goal_id, "boardId": board_id},
                "actiongoals_getActionGoal", opener)


def list_goals(settings, pod_token, board_id, limit=50, next_token=None, opener=None):
    from .operations import QUERY_ACTION_GOALS_BY_BOARD
    from .operations import QUERY_ACTION_GOALS_BY_BOARD_AFTER
    # The server rejects a null `after`, so the first page uses a document without it.
    variables = {"boardId": board_id, "first": limit}
    query = QUERY_ACTION_GOALS_BY_BOARD
    if next_token:
        variables["after"] = next_token
        query = QUERY_ACTION_GOALS_BY_BOARD_AFTER
    payload = _gql(settings, pod_token, query, variables,
                   "actiongoals_queryActionGoalsByBoardIdIndex", opener, allow_empty=True)
    payload = payload or {}
    return {"items": [g for g in (payload.get("items") or []) if g], "nextToken": payload.get("nextToken")}


def update_goal(settings, pod_token, board_id, goal_id, fields, opener=None):
    from .operations import MUTATION_UPDATE_ACTION_GOAL
    body = _compact(fields, _GOAL_KEYS)
    if not body:
        raise ValueError("nothing to update")
    body.update({"id": goal_id, "boardId": board_id})
    return _gql(settings, pod_token, MUTATION_UPDATE_ACTION_GOAL, {"input": body},
                "actiongoals_updateActionGoal", opener)


def delete_goal(settings, pod_token, board_id, goal_id, opener=None):
    from .operations import MUTATION_DELETE_ACTION_GOAL
    return _gql(settings, pod_token, MUTATION_DELETE_ACTION_GOAL,
                {"input": {"id": goal_id, "boardId": board_id}},
                "actiongoals_deleteActionGoal", opener)


# --------------------------------------------------------------------------- Files

def list_folders(settings, pod_token, board_id, limit=100, opener=None):
    from .operations import QUERY_FOLDERS_BY_BOARD
    payload = _gql(settings, pod_token, QUERY_FOLDERS_BY_BOARD, {"boardId": board_id, "first": limit},
                   "filemanager_foldersByBoardIdIndex", opener, allow_empty=True)
    return (payload or {}).get("items") or []


def create_folder(settings, pod_token, board_id, name, parent_folder_id=None, opener=None):
    from .operations import MUTATION_CREATE_FOLDER
    if not name or not name.strip():
        raise ValueError("folder name is required")
    body = {"boardId": board_id, "folderName": name.strip(), "createdBy": "user"}
    if parent_folder_id:
        body["parentFolderId"] = parent_folder_id
    return _gql(settings, pod_token, MUTATION_CREATE_FOLDER, {"input": body},
                "filemanager_createFolder", opener)


def list_files(settings, pod_token, board_id, folder_id, limit=50, opener=None):
    from .operations import QUERY_FILES_BY_BOARD_AND_FOLDER
    payload = _gql(settings, pod_token, QUERY_FILES_BY_BOARD_AND_FOLDER,
                   {"boardId": board_id, "folderId": folder_id, "limit": limit},
                   "filemanager_filesByBoardAndFolder", opener, allow_empty=True)
    return (payload or {}).get("items") or []


def get_file(settings, pod_token, file_id, opener=None):
    from .operations import QUERY_GET_FILE
    return _gql(settings, pod_token, QUERY_GET_FILE, {"id": file_id}, "filemanager_getFile", opener)


def delete_file(settings, pod_token, file_id, opener=None):
    from .operations import MUTATION_DELETE_FILE
    return _gql(settings, pod_token, MUTATION_DELETE_FILE, {"input": {"id": file_id}},
                "filemanager_deleteFile", opener)


def safe_basename(name):
    """Return a safe file name from a server-supplied name, or raise ValueError.

    Rejects empty names, ".", "..", separator-only names, absolute paths (leading slash or
    drive letter), and any ".." path component. Otherwise returns the last path component,
    with leading dots replaced by "_" so a server cannot create a dotfile (".zshenv" -> "_zshenv").
    """
    raw = str(name or "").replace("\\", "/").replace("\x00", "")
    parts = raw.split("/")
    if (
        not raw.strip()
        or raw.startswith("/")
        or re.match(r"^[A-Za-z]:", raw)
        or ".." in parts
        or not raw.strip("/ ")
    ):
        raise ValueError("unsafe or empty file name: %r" % raw[:80])
    base = raw.rstrip("/").split("/")[-1].strip()
    if not base or base == ".":
        raise ValueError("unsafe or empty file name: %r" % raw[:80])
    stripped = base.lstrip(".")
    return "_" * (len(base) - len(stripped)) + stripped


_BUCKET_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
_IPV4_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")
_REGION_RE = re.compile(r"^[a-z]{2}(-[a-z0-9]+)+$")


def _valid_bucket(bucket):
    """True when `bucket` follows S3 naming rules and cannot redirect a URL to another host."""
    return bool(
        isinstance(bucket, str)
        and _BUCKET_RE.match(bucket)
        and ".." not in bucket
        and not _IPV4_RE.match(bucket)
    )


def _bucket_region(bucket, opener=None):
    """Ask S3 which region hosts a bucket (public x-amz-bucket-region header on HEAD).

    Returns None, without any request, when the bucket name is not a valid S3 name, and
    None when the header is missing or not shaped like a region.
    """
    if not _valid_bucket(bucket):
        return None
    region = _head_bucket_region(bucket, opener)
    return region if isinstance(region, str) and _REGION_RE.match(region) else None


def _head_bucket_region(bucket, opener=None):
    req = urllib.request.Request("https://%s.s3.amazonaws.com/" % bucket, method="HEAD")
    open_fn = opener or urllib.request.urlopen
    try:
        with open_fn(req, timeout=15) as resp:
            headers = getattr(resp, "headers", None) or {}
            return headers.get("x-amz-bucket-region")
    except urllib.error.HTTPError as exc:
        # 403/301 still carry the header.
        return (exc.headers or {}).get("x-amz-bucket-region")
    except Exception:
        return None


def _pod_bucket(settings, pod_id, opener=None):
    """Return the pod's bucket name from pods_getMyPods (main-pool token), or None."""
    from .auth import ensure_main_token
    from .operations import QUERY_MY_PODS_STORAGE
    main_token = ensure_main_token(settings, interactive=False, opener=opener)
    payload = _gql(settings, main_token, QUERY_MY_PODS_STORAGE, {}, "pods_getMyPods", opener,
                   allow_empty=True)
    for pod in payload or []:
        if pod.get("podId") == pod_id:
            return pod.get("bucketName")
    return None


def _put_object(settings, bucket, key, body, content_type, region, opener):
    """Presign through the edge proxy and PUT; retry once in the bucket's real region on a redirect."""
    from .api import edge_presign
    open_fn = opener or urllib.request.urlopen
    tried = set()
    while True:
        tried.add(region)
        url, used_region = edge_presign(settings, bucket, key, "PUT", opener=opener, region=region)
        req = urllib.request.Request(url, data=body, headers={"Content-Type": content_type}, method="PUT")
        try:
            with open_fn(req, timeout=90) as resp:
                resp.read()
            return used_region or region
        except urllib.error.HTTPError as exc:
            real = (exc.headers or {}).get("x-amz-bucket-region")
            if not (isinstance(real, str) and _REGION_RE.match(real)):
                real = _bucket_region(bucket, opener)
            if exc.code in (301, 307, 400) and real and real not in tried:
                region = real
                continue
            raise RuntimeError("S3 PUT HTTP %s for %s (bucket %s, region %s)" % (exc.code, key, bucket, region))
        except (urllib.error.URLError, OSError) as exc:
            raise RuntimeError("S3 PUT network error for %s: %s" % (key, _scrub(getattr(exc, "reason", exc))))


def upload_file(settings, pod_token, pod_id, board_id, folder_id, path, note=None, tags=None,
                bucket=None, region=None, opener=None):
    from .operations import MUTATION_CREATE_FILE
    if not os.path.isfile(path):
        raise ValueError("not a file: %s" % path)
    file_name = os.path.basename(path)
    with open(path, "rb") as fh:
        body = fh.read()
    content_type = mimetypes.guess_type(file_name)[0] or "application/octet-stream"
    target_bucket = bucket or _pod_bucket(settings, pod_id, opener=opener) or settings.get("s3_bucket")
    if not target_bucket:
        raise RuntimeError("pod %s has no storage bucket" % pod_id)
    target_region = (
        region
        or (settings.get("cfg") or {}).get("pod_region")
        or _bucket_region(target_bucket, opener)
        or settings.get("s3_region")
    )
    key = "%s/%s/files/%d-%s" % (settings.get("s3_prefix") or "", board_id, int(time.time() * 1000), file_name)
    key = key.lstrip("/")
    final_region = _put_object(settings, target_bucket, key, body, content_type, target_region, opener)
    s3_uri = "s3://%s/%s" % (target_bucket, key)
    body_in = {
        "boardId": board_id,
        "folderId": folder_id,
        "fileName": file_name,
        "fileType": content_type,
        "fileSize": len(body),
        "url": "https://%s.s3.%s.amazonaws.com/%s" % (target_bucket, final_region, key),
        "s3Object": {"bucket": target_bucket, "key": key, "size": len(body),
                     "region": final_region, "s3_uri": s3_uri},
        "fileMetaData": json.dumps({"relPath": file_name, "source": "ab-cli"}),
    }
    if tags:
        body_in["tags"] = list(tags)
    if note:
        body_in["note"] = note
    return _gql(settings, pod_token, MUTATION_CREATE_FILE, {"input": body_in},
                "filemanager_createFile", opener)


def download_file(settings, pod_token, file_id, out_dir, overwrite=False, opener=None):
    from .api import download_bytes_via_edge
    record = get_file(settings, pod_token, file_id, opener=opener)
    s3 = record.get("s3Object") or {}
    if not s3.get("bucket") or not s3.get("key"):
        raise RuntimeError("file %s has no stored object to download" % file_id)
    name = safe_basename(record.get("fileName"))
    root = os.path.realpath(out_dir)
    if not os.path.isdir(root):
        raise ValueError("output directory does not exist: %s" % out_dir)
    target = os.path.join(root, name)
    if os.path.dirname(os.path.realpath(target)) != root:
        raise ValueError("refusing to write outside the output directory")
    if os.path.islink(target):
        raise ValueError("refusing to write through a symbolic link: %s" % target)
    if os.path.lexists(target) and not overwrite:
        raise FileExistsError("%s already exists; pass overwrite to replace it" % target)
    region = s3.get("region") or settings.get("s3_region")
    try:
        data = download_bytes_via_edge(settings, s3["bucket"], s3["key"], opener=opener, region=region)
    except RuntimeError as first:
        real = _bucket_region(s3["bucket"], opener)
        if not real or real == region:
            raise RuntimeError(_scrub(first))
        data = download_bytes_via_edge(settings, s3["bucket"], s3["key"], opener=opener, region=real)
    if overwrite:
        fd, tmp = tempfile.mkstemp(dir=root)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            os.chmod(tmp, 0o644)
            if os.path.islink(target):
                raise ValueError("refusing to write through a symbolic link: %s" % target)
            os.replace(tmp, target)
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
    else:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        try:
            fd = os.open(target, flags, 0o644)
        except FileExistsError:
            raise FileExistsError("%s already exists; pass overwrite to replace it" % target)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
    return {"path": target, "fileName": name, "size": len(data), "id": file_id}
