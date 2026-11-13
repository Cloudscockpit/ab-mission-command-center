#!/usr/bin/env python3
"""Submit ActionBoard mission brief, plan, and report documents from the CLI.

Python 3.9+ standard library only (zero third-party pip dependencies).
Handles:
  1. AppSync GraphQL authentication (`auth_login`, `auth_refreshToken`)
  2. Pod discovery (`pods_getMyPods`) and Pod-pool SSO token exchange
     (`pods_createExchangeCode` -> `pods_consumeExchangeCode`)
  3. Board discovery (`boards_getMyBoards`) and interactive Pod/Board selection
  4. Mission listing, creation, and update (`assistprofile_listMissionsByBoard`,
     `assistprofile_createMission`, `assistprofile_updateMission`)
  5. Mission Plan submission (`assistprofile_createMissionPlan`,
     `assistprofile_updateMissionPlan`, `assistprofile_submitMissionPlan`)
  6. S3 deliverable upload (pure-stdlib AWS SigV4 PUT) + Mission Report
     registration (`assistprofile_submitReports`, with `filemanager_createFile`
     fallback for legacy missions without `missionFolderId`)

Credentials and cached tokens are stored with 0600 permissions in
`~/.actionboard/credentials.json` (or `$ACTIONBOARD_CREDENTIALS_FILE`).
Project-level Pod/Board/Mission defaults are stored in `.actionboard/config.json`.
"""

import argparse
import base64
import configparser
import datetime
import getpass
import hashlib
import hmac
import json
import mimetypes
import os
import re
import stat
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

sys.dont_write_bytecode = True

DEFAULT_S3_REGION = "ap-southeast-1"
DEFAULT_S3_BUCKET = "actionboard-kb-agent"
DEFAULT_S3_PREFIX = "PremiumBoardKB/Boards/Investor+Boards"
DEFAULT_COGNITO_DOMAIN = "https://absaas-dev.auth.ap-southeast-1.amazoncognito.com/"

MISSION_FILES = [
    ("mission-report.md", "text/markdown", ["mission", "report"], "Mission Report (Markdown)"),
    ("mission-report.html", "text/html", ["mission", "report", "dashboard"], "Mission Analytics Dashboard (HTML)"),
    ("mission-report.jsonld", "application/ld+json", ["mission", "report", "jsonld"], "Mission Report Knowledge Graph (JSON-LD)"),
    ("mission-brief.md", "text/markdown", ["mission", "brief"], "Mission Brief (Markdown)"),
    ("mission-brief.jsonld", "application/ld+json", ["mission", "brief", "jsonld"], "Mission Brief Knowledge Graph (JSON-LD)"),
    ("mission-plan.md", "text/markdown", ["mission", "plan"], "Mission Plan (Markdown)"),
    ("mission-plan.jsonld", "application/ld+json", ["mission", "plan", "jsonld"], "Mission Plan Knowledge Graph (JSON-LD)"),
    ("mission-metrics.json", "application/json", ["mission", "metrics"], "Mission Metrics (JSON)"),
]


def fail(message, code=2):
    sys.stderr.write("submit_mission: %s\n" % " ".join(str(message).split()))
    sys.exit(code)


def info(message):
    sys.stdout.write("%s\n" % message)


def warn(message):
    sys.stderr.write("submit_mission: WARNING: %s\n" % message)


# --------------------------------------------------------- credential & config

def default_credentials_path():
    env_path = os.environ.get("ACTIONBOARD_CREDENTIALS_FILE")
    if env_path:
        return os.path.abspath(os.path.expanduser(env_path))
    home_cred = os.path.join(os.path.expanduser("~"), ".actionboard", "credentials.json")
    local_cred = os.path.abspath(os.path.join(".actionboard", "credentials.json"))
    try:
        if os.path.exists(home_cred) and os.access(home_cred, os.R_OK):
            return home_cred
    except OSError:
        pass
    if os.path.exists(local_cred):
        return local_cred
    return home_cred


def load_json_file(path):
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError) as exc:
        warn("could not read %s: %s" % (path, exc))
        return {}


def save_secure_json(path, data):
    target_path = os.path.abspath(path)
    home_default = os.path.abspath(os.path.join(os.path.expanduser("~"), ".actionboard", "credentials.json"))
    parent = os.path.dirname(target_path)
    try:
        os.makedirs(parent, exist_ok=True)
    except OSError:
        if target_path == home_default:
            target_path = os.path.abspath(os.path.join(".actionboard", "credentials.json"))
            parent = os.path.dirname(target_path)
            os.makedirs(parent, exist_ok=True)
        else:
            raise
    try:
        os.chmod(parent, 0o700)
    except OSError:
        pass
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(dir=parent, prefix=".cred-", suffix=".tmp")
        try:
            os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
        except (AttributeError, OSError):
            pass
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
            fh.write("\n")
        try:
            os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
        os.replace(tmp, target_path)
        return target_path
    except OSError as exc:
        if tmp and os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass
        if target_path == home_default:
            fallback = os.path.abspath(os.path.join(".actionboard", "credentials.json"))
            return save_secure_json(fallback, data)
        fail("cannot write %s: %s" % (target_path, exc))


def save_config_json(path, data):
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(dir=parent, prefix=".cfg-", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
        os.replace(tmp, path)
    except OSError as exc:
        if tmp and os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass
        fail("cannot write %s: %s" % (path, exc))


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

    return {
        "cred_file": cred_file,
        "creds": creds,
        "config_file": config_path,
        "cfg": cfg,
        "endpoint": endpoint,
        "api_key": api_key,
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


# --------------------------------------------------------------- GraphQL client

def graphql_request(endpoint, api_key, query, variables=None, bearer_token=None, opener=None):
    if not endpoint:
        fail(
            "AppSync endpoint is not configured. Run `python submit_mission.py configure "
            "--endpoint <url> --api-key <key>` or set APPSYNC_GRAPHQL_ENDPOINT."
        )
    if not api_key:
        fail(
            "AppSync API key is not configured. Run `python submit_mission.py configure "
            "--endpoint <url> --api-key <key>` or set APPSYNC_API_KEY."
        )

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "x-api-key": api_key,
        "User-Agent": "ActionBoard-CLI/1.2",
    }
    if bearer_token:
        headers["Authorization"] = "Bearer %s" % bearer_token

    payload = {"query": query, "variables": variables or {}}
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
    open_fn = opener or urllib.request.urlopen

    try:
        with open_fn(req, timeout=30) as resp:
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


# --------------------------------------------------------- Auth & Pod Exchange

MUTATION_LOGIN = """
mutation Auth_login($input: Auth_LoginInput!) {
  auth_login(input: $input) {
    success
    message
    data {
      tokens {
        accessToken
        idToken
        refreshToken
        expiresIn
        tokenType
      }
      user {
        profileId
        userId
        email
        name
      }
    }
  }
}
"""

MUTATION_REFRESH = """
mutation Auth_refreshToken($input: Auth_RefreshTokenInput!) {
  auth_refreshToken(input: $input) {
    success
    message
    data {
      tokens {
        accessToken
        idToken
        refreshToken
        expiresIn
      }
      user {
        profileId
        userId
        email
        name
      }
    }
  }
}
"""

QUERY_ME = """
query Auth_me {
  auth_me {
    success
    message
    data {
      user {
        profileId
        userId
        email
        name
      }
    }
  }
}
"""

QUERY_MY_PODS = """
query Pods_getMyPods {
  pods_getMyPods {
    success
    message
    data {
      podId
      podName
      slug
      hostname
      bucketName
      status
      memberRole
      memberStatus
    }
  }
}
"""

MUTATION_CREATE_EXCHANGE_CODE = """
mutation Pods_createExchangeCode($podId: String!, $returnUrl: String!) {
  pods_createExchangeCode(podId: $podId, returnUrl: $returnUrl) {
    success
    message
    data {
      code
    }
  }
}
"""

MUTATION_CONSUME_EXCHANGE_CODE = """
mutation Pods_consumeExchangeCode($code: String!, $podId: String!) {
  pods_consumeExchangeCode(code: $code, podId: $podId) {
    success
    message
    data {
      token
      idToken
      accessToken
      refreshToken
      expiresIn
      userId
      email
      username
    }
  }
}
"""

QUERY_MY_BOARDS = """
query Boards_getMyBoards($podId: String, $searchTerm: String) {
  boards_getMyBoards(podId: $podId, searchTerm: $searchTerm) {
    success
    message
    data {
      boardId
      name
      description
      ownerId
      podId
      memberCount
      boardStatus
      boardType
      createdAt
      updatedAt
    }
  }
}
"""

QUERY_LIST_MISSIONS_BY_BOARD = """
query Assistprofile_listMissionsByBoard($boardId: ID!, $limit: Int, $nextToken: String) {
  assistprofile_listMissionsByBoard(boardId: $boardId, limit: $limit, nextToken: $nextToken) {
    nextToken
    items {
      boardId
      missionId
      ownerProfileId
      assignedAgentProfileId
      title
      shortDescription
      startDate
      endDate
      status
      available2AAgent
      invitationMode
      totalInvited
      totalAccepted
      totalPlansSubmitted
      selectionStatus
      selectedProfileId
      selectedPlanId
      selectedAt
      createdAt
      updatedAt
      missionFolderId
      reportsSubfolderId
      totalFiles
    }
  }
}
"""

QUERY_GET_MISSION_INVITATION = """
query Assistprofile_getMissionInvitation($invitationId: ID!, $boardId: ID!) {
  assistprofile_getMissionInvitation(invitationId: $invitationId, boardId: $boardId) {
    invitationId
    missionId
    boardId
    invitedProfileId
    invitedBy
    status
    message
    expiresAt
    acceptedAt
    declinedAt
    declineReason
    planId
    planSubmittedAt
    createdAt
    updatedAt
  }
}
"""

QUERY_GET_MY_MISSION_INVITATIONS = """
query Assistprofile_getMyMissionInvitations($status: Assistprofile_MissionInvitationStatus, $limit: Int, $nextToken: String) {
  assistprofile_getMyMissionInvitations(status: $status, limit: $limit, nextToken: $nextToken) {
    nextToken
    items {
      invitationId
      missionId
      boardId
      invitedProfileId
      invitedBy
      status
      message
      expiresAt
      acceptedAt
      declinedAt
      declineReason
      planId
      planSubmittedAt
      createdAt
      updatedAt
    }
  }
}
"""

MUTATION_ACCEPT_MISSION_INVITATION = """
mutation Assistprofile_acceptMissionInvitation($invitationId: ID!, $boardId: ID!) {
  assistprofile_acceptMissionInvitation(invitationId: $invitationId, boardId: $boardId) {
    invitationId
    missionId
    boardId
    invitedProfileId
    invitedBy
    status
    acceptedAt
    updatedAt
  }
}
"""

QUERY_GET_MISSION = """
query Assistprofile_getMission($boardId: ID!, $missionId: ID!) {
  assistprofile_getMission(boardId: $boardId, missionId: $missionId) {
    boardId
    missionId
    ownerProfileId
    assignedAgentProfileId
    title
    shortDescription
    startDate
    endDate
    status
    available2AAgent
    invitationMode
    totalInvited
    totalAccepted
    totalPlansSubmitted
    selectionStatus
    selectedProfileId
    selectedPlanId
    selectedAt
    createdAt
    updatedAt
    missionFolderId
    reportsSubfolderId
    totalFiles
  }
}
"""

QUERY_LIST_MISSIONS_BY_AGENT = """
query Assistprofile_listMissionsByAgent($actionAssistAgentId: ID!, $limit: Int, $nextToken: String) {
  assistprofile_listMissionsByAgent(actionAssistAgentId: $actionAssistAgentId, limit: $limit, nextToken: $nextToken) {
    nextToken
    items {
      boardId
      missionId
      ownerProfileId
      assignedAgentProfileId
      title
      shortDescription
      startDate
      endDate
      status
      available2AAgent
      invitationMode
      selectionStatus
      selectedProfileId
      selectedPlanId
      createdAt
      updatedAt
      missionFolderId
      reportsSubfolderId
      totalFiles
    }
  }
}
"""

QUERY_GET_MISSION_PLAN = """
query Assistprofile_getMissionPlan($missionId: ID!, $planId: ID!) {
  assistprofile_getMissionPlan(missionId: $missionId, planId: $planId) {
    missionId
    planId
    boardId
    ownerProfileId
    createdByProfileId
    assignedAgentProfileId
    lastEditedByProfileId
    plan
    status
    invitationId
    submittedByProfileId
    reviewStatus
    reviewNotes
    selectionReason
    createdAt
    updatedAt
  }
}
"""

QUERY_LIST_MISSION_PLANS_BY_MISSION = """
query Assistprofile_listMissionPlansByMission($missionId: ID!, $limit: Int, $nextToken: String) {
  assistprofile_listMissionPlansByMission(missionId: $missionId, limit: $limit, nextToken: $nextToken) {
    nextToken
    items {
      missionId
      planId
      boardId
      ownerProfileId
      createdByProfileId
      assignedAgentProfileId
      lastEditedByProfileId
      plan
      status
      invitationId
      submittedByProfileId
      reviewStatus
      reviewNotes
      selectionReason
      createdAt
      updatedAt
    }
  }
}
"""

QUERY_FILES_BY_BOARD_AND_FOLDER = """
query Filemanager_filesByBoardAndFolder($boardId: ID!, $folderId: ID!, $limit: Int, $nextToken: String) {
  filemanager_filesByBoardAndFolder(boardId: $boardId, folderId: $folderId, limit: $limit, nextToken: $nextToken) {
    success
    message
    data {
      nextToken
      items {
        id
        boardId
        folderId
        fileName
        fileType
        fileSize
        url
        note
        tags
        s3Object {
          bucket
          key
          size
          region
          s3_uri
        }
        createdAt
        updatedAt
      }
    }
  }
}
"""

MUTATION_CREATE_MISSION = """
mutation Assistprofile_createMission($input: Assistprofile_CreateMissionInput!) {
  assistprofile_createMission(input: $input) {
    boardId
    missionId
    ownerProfileId
    assignedAgentProfileId
    title
    shortDescription
    startDate
    endDate
    status
    missionFolderId
    reportsSubfolderId
    totalFiles
    createdAt
    updatedAt
  }
}
"""

MUTATION_UPDATE_MISSION = """
mutation Assistprofile_updateMission($input: Assistprofile_UpdateMissionInput!) {
  assistprofile_updateMission(input: $input) {
    boardId
    missionId
    ownerProfileId
    assignedAgentProfileId
    title
    shortDescription
    startDate
    endDate
    status
    missionFolderId
    reportsSubfolderId
    totalFiles
    createdAt
    updatedAt
  }
}
"""

MUTATION_UPDATE_MISSION_STATUS = """
mutation Assistprofile_updateMissionStatus($input: Assistprofile_UpdateMissionStatusInput!) {
  assistprofile_updateMissionStatus(input: $input) {
    boardId
    missionId
    status
    updatedAt
  }
}
"""

MUTATION_DELETE_MISSION = """
mutation Assistprofile_deleteMission($boardId: ID!, $missionId: ID!) {
  assistprofile_deleteMission(boardId: $boardId, missionId: $missionId)
}
"""

MUTATION_CREATE_MISSION_PLAN = """
mutation Assistprofile_createMissionPlan($input: Assistprofile_CreateMissionPlanInput!) {
  assistprofile_createMissionPlan(input: $input) {
    missionId
    planId
    boardId
    ownerProfileId
    createdByProfileId
    assignedAgentProfileId
    lastEditedByProfileId
    plan
    status
    invitationId
    submittedByProfileId
    reviewStatus
    createdAt
    updatedAt
  }
}
"""

MUTATION_UPDATE_MISSION_PLAN = """
mutation Assistprofile_updateMissionPlan($input: Assistprofile_UpdateMissionPlanInput!) {
  assistprofile_updateMissionPlan(input: $input) {
    missionId
    planId
    boardId
    ownerProfileId
    createdByProfileId
    assignedAgentProfileId
    lastEditedByProfileId
    plan
    status
    updatedAt
  }
}
"""

MUTATION_SUBMIT_MISSION_PLAN = """
mutation Assistprofile_submitMissionPlan($input: Assistprofile_SubmitMissionPlanInput!) {
  assistprofile_submitMissionPlan(input: $input) {
    missionId
    planId
    boardId
    ownerProfileId
    createdByProfileId
    submittedByProfileId
    assignedAgentProfileId
    invitationId
    plan
    status
    reviewStatus
    createdAt
    updatedAt
  }
}
"""

MUTATION_SUBMIT_REPORTS = """
mutation Assistprofile_submitReports($input: Assistprofile_SubmitReportsInput!) {
  assistprofile_submitReports(input: $input) {
    success
    message
    totalFiles
    files {
      id
      boardId
      folderId
      fileName
      fileType
      fileSize
      url
      note
      tags
      createdAt
      updatedAt
    }
  }
}
"""

QUERY_FOLDERS_BY_BOARD = """
query Filemanager_foldersByBoardIdIndex($boardId: ID!, $first: Int) {
  filemanager_foldersByBoardIdIndex(boardId: $boardId, first: $first) {
    success
    message
    data {
      items {
        id
        boardId
        folderName
        parentFolderId
      }
    }
  }
}
"""

MUTATION_CREATE_FOLDER = """
mutation Filemanager_createFolder($input: Filemanager_CreateFileManagerFolderInput!) {
  filemanager_createFolder(input: $input) {
    success
    message
    data {
      id
      boardId
      folderName
      parentFolderId
    }
  }
}
"""

MUTATION_CREATE_FILE = """
mutation Filemanager_createFile($input: Filemanager_CreateFileManagerFileInput!) {
  filemanager_createFile(input: $input) {
    success
    message
    data {
      id
      boardId
      folderId
      fileName
      fileType
      fileSize
      url
    }
  }
}
"""


def login_with_credentials(settings, email, password, opener=None):
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


def ensure_main_token(settings, interactive=True, opener=None):
    env_token = os.environ.get("ACTIONBOARD_ACCESS_TOKEN")
    if env_token:
        return env_token

    creds = settings["creds"]
    access_token = creds.get("access_token")
    if access_token and token_is_valid(access_token):
        return access_token

    refresh_token = creds.get("refresh_token")
    email = os.environ.get("ACTIONBOARD_EMAIL") or creds.get("email")
    if refresh_token and email:
        try:
            data = graphql_request(
                settings["endpoint"],
                settings["api_key"],
                MUTATION_REFRESH,
                {"input": {"refreshToken": refresh_token, "username": email}},
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
    env_pod_token = os.environ.get("ACTIONBOARD_POD_ID_TOKEN")
    if env_pod_token:
        return env_pod_token

    creds = settings["creds"]
    pod_tokens = creds.get("pod_tokens") or {}
    cached = pod_tokens.get(pod_id) or {}
    if cached.get("id_token") and token_is_valid(cached["id_token"]):
        return cached["id_token"]

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


def fetch_my_boards(settings, pod_id_token, pod_id=None, search_term=None, opener=None):
    variables = {}
    if pod_id:
        variables["podId"] = pod_id
    if search_term:
        variables["searchTerm"] = search_term
    data = graphql_request(
        settings["endpoint"],
        settings["api_key"],
        QUERY_MY_BOARDS,
        variables,
        bearer_token=pod_id_token,
        opener=opener,
    )
    res = data.get("boards_getMyBoards") or {}
    if not res.get("success"):
        fail("failed to fetch boards: %s" % (res.get("message") or "unknown error"))
    return res.get("data") or []


def fetch_missions_by_board(settings, pod_id_token, board_id, limit=25, opener=None):
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
    variables = {"limit": limit}
    if status:
        variables["status"] = status
    data = graphql_request(
        settings["endpoint"],
        settings["api_key"],
        QUERY_GET_MY_MISSION_INVITATIONS,
        variables,
        bearer_token=pod_id_token,
        opener=opener,
    )
    conn = data.get("assistprofile_getMyMissionInvitations") or {}
    return conn.get("items") or []


def fetch_mission(settings, pod_id_token, board_id, mission_id, opener=None):
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


# --------------------------------------------------------- Pure-stdlib S3 SigV4

def _sign(key, msg):
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _get_signature_key(secret_key, date_stamp, region_name, service_name):
    k_date = _sign(("AWS4" + secret_key).encode("utf-8"), date_stamp)
    k_region = _sign(k_date, region_name)
    k_service = _sign(k_region, service_name)
    k_signing = _sign(k_service, "aws4_request")
    return k_signing


def upload_bytes_to_s3(bucket, region, key, body_bytes, content_type, aws_creds, metadata=None, opener=None):
    """Upload bytes to S3 using AWS Signature Version 4 (standard library only)."""
    if not aws_creds or not aws_creds.get("access_key") or not aws_creds.get("secret_key"):
        raise RuntimeError(
            "AWS credentials not found for S3 upload. Set AWS_ACCESS_KEY_ID and "
            "AWS_SECRET_ACCESS_KEY, configure ~/.aws/credentials, or run "
            "`python submit_mission.py configure --aws-access-key-id ... --aws-secret-access-key ...`."
        )

    now = datetime.datetime.now(datetime.timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")

    host = "%s.s3.%s.amazonaws.com" % (bucket, region)
    # Encode URI path segments per RFC 3986
    canonical_uri = "/" + "/".join(urllib.parse.quote(seg, safe="-_.~") for seg in key.lstrip("/").split("/"))
    payload_hash = hashlib.sha256(body_bytes).hexdigest()

    headers_to_sign = {
        "content-type": content_type,
        "host": host,
        "x-amz-content-sha256": payload_hash,
        "x-amz-date": amz_date,
    }
    if aws_creds.get("session_token"):
        headers_to_sign["x-amz-security-token"] = aws_creds["session_token"]

    if metadata:
        for mk, mv in metadata.items():
            clean_k = re.sub(r"[^a-z0-9_-]", "", str(mk).lower())
            clean_v = re.sub(r"[^\x20-\x7e]", "", str(mv)).strip()
            if clean_k and clean_v:
                headers_to_sign["x-amz-meta-" + clean_k] = clean_v

    sorted_header_keys = sorted(headers_to_sign.keys())
    canonical_headers = "".join("%s:%s\n" % (k, headers_to_sign[k]) for k in sorted_header_keys)
    signed_headers = ";".join(sorted_header_keys)

    canonical_request = "\n".join([
        "PUT",
        canonical_uri,
        "",
        canonical_headers,
        signed_headers,
        payload_hash,
    ])

    algorithm = "AWS4-HMAC-SHA256"
    credential_scope = "%s/%s/s3/aws4_request" % (date_stamp, region)
    string_to_sign = "\n".join([
        algorithm,
        amz_date,
        credential_scope,
        hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
    ])

    signing_key = _get_signature_key(aws_creds["secret_key"], date_stamp, region, "s3")
    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    authorization_header = (
        "%s Credential=%s/%s, SignedHeaders=%s, Signature=%s"
        % (algorithm, aws_creds["access_key"], credential_scope, signed_headers, signature)
    )

    url = "https://%s%s" % (host, canonical_uri)
    req_headers = {k: v for k, v in headers_to_sign.items() if k != "host"}
    req_headers["Authorization"] = authorization_header
    req_headers["Content-Length"] = str(len(body_bytes))

    req = urllib.request.Request(url, data=body_bytes, headers=req_headers, method="PUT")
    open_fn = opener or urllib.request.urlopen
    try:
        with open_fn(req, timeout=60) as resp:
            resp.read()
    except urllib.error.HTTPError as exc:
        err_body = ""
        try:
            err_body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        raise RuntimeError("S3 PUT HTTP %s for %s: %s" % (exc.code, url, err_body or exc.reason))
    except urllib.error.URLError as exc:
        raise RuntimeError("S3 network error for %s: %s" % (url, exc.reason))

    return {
        "bucket": bucket,
        "key": key.lstrip("/"),
        "size": len(body_bytes),
        "region": region,
        "s3_uri": "s3://%s/%s" % (bucket, key.lstrip("/")),
        "url": "https://%s/%s" % (host, key.lstrip("/")),
    }


def download_bytes_from_s3(bucket, region, key, aws_creds, opener=None):
    """Download bytes from S3 using AWS Signature Version 4 GET (standard library only)."""
    if not aws_creds or not aws_creds.get("access_key") or not aws_creds.get("secret_key"):
        raise RuntimeError("AWS credentials not configured for S3 download")

    now = datetime.datetime.now(datetime.timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")

    host = "%s.s3.%s.amazonaws.com" % (bucket, region)
    canonical_uri = "/" + "/".join(urllib.parse.quote(seg, safe="-_.~") for seg in key.lstrip("/").split("/"))
    payload_hash = hashlib.sha256(b"").hexdigest()

    headers_to_sign = {
        "host": host,
        "x-amz-content-sha256": payload_hash,
        "x-amz-date": amz_date,
    }
    if aws_creds.get("session_token"):
        headers_to_sign["x-amz-security-token"] = aws_creds["session_token"]

    sorted_header_keys = sorted(headers_to_sign.keys())
    canonical_headers = "".join("%s:%s\n" % (k, headers_to_sign[k]) for k in sorted_header_keys)
    signed_headers = ";".join(sorted_header_keys)

    canonical_request = "\n".join([
        "GET",
        canonical_uri,
        "",
        canonical_headers,
        signed_headers,
        payload_hash,
    ])

    algorithm = "AWS4-HMAC-SHA256"
    credential_scope = "%s/%s/s3/aws4_request" % (date_stamp, region)
    string_to_sign = "\n".join([
        algorithm,
        amz_date,
        credential_scope,
        hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
    ])

    signing_key = _get_signature_key(aws_creds["secret_key"], date_stamp, region, "s3")
    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    authorization_header = (
        "%s Credential=%s/%s, SignedHeaders=%s, Signature=%s"
        % (algorithm, aws_creds["access_key"], credential_scope, signed_headers, signature)
    )

    url = "https://%s%s" % (host, canonical_uri)
    req_headers = {k: v for k, v in headers_to_sign.items() if k != "host"}
    req_headers["Authorization"] = authorization_header

    req = urllib.request.Request(url, headers=req_headers, method="GET")
    open_fn = opener or urllib.request.urlopen
    with open_fn(req, timeout=60) as resp:
        return resp.read()


def slugify_title(title, fallback_id="mission"):
    raw = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
    if not raw:
        raw = "mission-%s" % str(fallback_id)[:8].lower()
    return raw[:64].rstrip("-")


def materialize_fetched_mission_docs(out_dir, slug, mission, plan_obj=None, downloaded_files=None):
    """Write mission-brief.md, mission-brief.jsonld, and mission-plan.md into out_dir."""
    os.makedirs(out_dir, exist_ok=True)
    downloaded_files = downloaded_files or {}
    written_files = []

    title = (mission.get("title") or slug).strip()
    short_desc = (mission.get("shortDescription") or "").strip()
    mission_id = mission.get("missionId") or ""
    board_id = mission.get("boardId") or ""
    start_date = mission.get("startDate") or mission.get("createdAt") or ""
    end_date = mission.get("endDate") or ""
    status = mission.get("status") or "INITIATED"

    plan_text = ((plan_obj or {}).get("plan") or "").strip()
    brief_md_bytes = downloaded_files.get("mission-brief.md")
    plan_md_bytes = downloaded_files.get("mission-plan.md")

    brief_md_text = brief_md_bytes.decode("utf-8", errors="replace").strip() if brief_md_bytes else ""
    plan_md_text = plan_md_bytes.decode("utf-8", errors="replace").strip() if plan_md_bytes else ""

    # If plan_text has both Mission Brief and Mission Plan separated by `---`, split them cleanly
    if not brief_md_text and not plan_md_text and plan_text:
        parts = re.split(r"\n+---\n+", plan_text, maxsplit=1)
        if len(parts) == 2 and re.search(r"^#\s+.*Brief", parts[0], re.I | re.M):
            brief_md_text = parts[0].strip()
            plan_md_text = parts[1].strip()
        elif re.search(r"^#\s+.*Brief", plan_text, re.I | re.M) and not re.search(r"^#\s+.*Plan", plan_text, re.I | re.M):
            brief_md_text = plan_text
        else:
            plan_md_text = plan_text

    if not brief_md_text:
        lines = [
            "# Mission Brief — %s" % title,
            "",
            "| Field | Value |",
            "|---|---|",
            "| **Mission ID** | `%s` |" % mission_id,
            "| **Board ID** | `%s` |" % board_id,
            "| **Status** | `%s` |" % status,
        ]
        if start_date:
            lines.append("| **Start Date** | `%s` |" % start_date)
        if end_date:
            lines.append("| **End Date** | `%s` |" % end_date)
        lines.extend([
            "",
            "## Objective",
            "",
            short_desc or ("Complete assigned ActionBoard mission: %s" % title),
            "",
            "## Success Criteria",
            "",
            "- Deliver the implementation and verification requested in the assigned mission.",
            "- Record outcomes and submit the completed Mission Report back to the ActionBoard board.",
            "",
        ])
        brief_md_text = "\n".join(lines)

    if not plan_md_text:
        lines = [
            "# Mission Plan — %s" % title,
            "",
            "## Context",
            "",
            short_desc or ("Assigned mission `%s` on board `%s`." % (mission_id, board_id)),
            "",
            "## Execution Waves",
            "",
            "1. **Wave 1 — Recon & Design:** Inspect affected modules and refine task breakdown.",
            "2. **Wave 2 — Implementation:** Execute code/data changes for `%s`." % title,
            "3. **Wave 3 — Verification & Report:** Run test suites, generate `mission-report.md` / `mission-report.html`, and run `submit_mission.py submit`.",
            "",
        ]
        plan_md_text = "\n".join(lines)

    brief_path = os.path.join(out_dir, "mission-brief.md")
    with open(brief_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(brief_md_text.rstrip() + "\n")
    written_files.append("mission-brief.md")

    plan_path = os.path.join(out_dir, "mission-plan.md")
    with open(plan_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(plan_md_text.rstrip() + "\n")
    written_files.append("mission-plan.md")

    # Write downloaded JSON-LD files if present, or synthesize mission-brief.jsonld
    if "mission-brief.jsonld" in downloaded_files:
        with open(os.path.join(out_dir, "mission-brief.jsonld"), "wb") as fh:
            fh.write(downloaded_files["mission-brief.jsonld"])
        written_files.append("mission-brief.jsonld")
    else:
        project_node = {
            "@id": "urn:voltron:mission:%s" % slug,
            "@type": "Project",
            "name": title,
            "description": short_desc or ("ActionBoard mission: %s" % title),
            "identifier": mission_id,
        }
        if start_date:
            project_node["startDate"] = start_date
        if end_date:
            project_node["endDate"] = end_date
        brief_jsonld = {
            "@context": "https://schema.org",
            "@graph": [project_node],
        }
        with open(os.path.join(out_dir, "mission-brief.jsonld"), "w", encoding="utf-8", newline="\n") as fh:
            json.dump(brief_jsonld, fh, indent=2)
            fh.write("\n")
        written_files.append("mission-brief.jsonld")

    for extra_name in ("mission-plan.jsonld", "mission-report.md", "mission-report.jsonld", "mission-report.html", "mission-metrics.json"):
        if extra_name in downloaded_files and extra_name not in written_files:
            with open(os.path.join(out_dir, extra_name), "wb") as fh:
                fh.write(downloaded_files[extra_name])
            written_files.append(extra_name)

    return written_files


# --------------------------------------------------------- Mission doc parsing

def find_latest_mission_dir(base_dir="."):
    candidates = []
    for folder in ("actionboard-v5-missions", os.path.join("docs", "missions")):
        root = os.path.join(base_dir, folder)
        if not os.path.isdir(root):
            continue
        for entry in sorted(os.listdir(root)):
            full = os.path.join(root, entry)
            if os.path.isdir(full):
                has_doc = any(
                    os.path.exists(os.path.join(full, name))
                    for name in ("mission-report.md", "mission-plan.md", "mission-brief.md")
                )
                if has_doc:
                    candidates.append(full)
    if not candidates:
        return None
    candidates.sort(key=lambda p: (os.path.basename(p), os.path.getmtime(p)))
    return candidates[-1]


def parse_mission_metadata(mission_dir):
    """Extract slug, title, objective/shortDescription, and dates from a mission directory."""
    folder_name = os.path.basename(os.path.abspath(mission_dir.rstrip("/\\")))
    slug = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", folder_name)
    title = slug.replace("-", " ").strip().title() or "ActionBoard Mission"
    short_description = ""
    start_date = None
    end_date = None

    for jsonld_name in ("mission-report.jsonld", "mission-plan.jsonld", "mission-brief.jsonld"):
        jpath = os.path.join(mission_dir, jsonld_name)
        if os.path.exists(jpath):
            data = load_json_file(jpath)
            graph = data.get("@graph") if isinstance(data.get("@graph"), list) else []
            for node in graph:
                if not isinstance(node, dict):
                    continue
                if node.get("@type") == "Project" or str(node.get("@id", "")).startswith("urn:voltron:mission:"):
                    node_id = str(node.get("@id") or "")
                    if node_id.startswith("urn:voltron:mission:"):
                        slug = node_id.split("urn:voltron:mission:", 1)[1] or slug
                    if isinstance(node.get("name"), str) and node["name"].strip():
                        title = node["name"].strip()
                    if isinstance(node.get("description"), str) and node["description"].strip():
                        short_description = node["description"].strip()
                    if isinstance(node.get("startDate"), str):
                        start_date = node["startDate"].strip()
                    if isinstance(node.get("endDate"), str):
                        end_date = node["endDate"].strip()
                    break

    metrics_path = os.path.join(mission_dir, "mission-metrics.json")
    if os.path.exists(metrics_path):
        metrics = load_json_file(metrics_path)
        timing = metrics.get("timing") if isinstance(metrics.get("timing"), dict) else {}
        if not start_date and isinstance(timing.get("started_at"), str):
            start_date = timing["started_at"]
        if not end_date and isinstance(timing.get("ended_at"), str):
            end_date = timing["ended_at"]

    brief_md = os.path.join(mission_dir, "mission-brief.md")
    if os.path.exists(brief_md):
        try:
            with open(brief_md, encoding="utf-8") as fh:
                text = fh.read()
            m_h1 = re.search(r"^#\s+(.+)$", text, re.M)
            if m_h1:
                h1 = re.sub(r"^Mission Brief\s*[:\u2014-]\s*", "", m_h1.group(1).strip(), flags=re.I)
                if h1:
                    title = h1
            if not short_description:
                m_obj = re.search(r"^##\s+Objective\s*\n+(.+?)(?:\n\n|\n##|\Z)", text, re.M | re.S)
                if m_obj:
                    short_description = " ".join(m_obj.group(1).strip().split())
        except OSError:
            pass

    if not short_description:
        for md_name in ("mission-report.md", "mission-plan.md"):
            md_path = os.path.join(mission_dir, md_name)
            if os.path.exists(md_path):
                try:
                    with open(md_path, encoding="utf-8") as fh:
                        lines = [ln.strip() for ln in fh.read().splitlines() if ln.strip()]
                    if lines and lines[0].startswith("# "):
                        h1 = re.sub(
                            r"^Mission (?:Report|Plan)\s*[:\u2014-]\s*",
                            "",
                            lines[0][2:].strip(),
                            flags=re.I,
                        )
                        if h1 and title == slug.replace("-", " ").title():
                            title = h1
                    for ln in lines[1:]:
                        if not ln.startswith("#") and not ln.startswith("|") and not ln.startswith(">"):
                            short_description = ln[:500]
                            break
                except OSError:
                    pass
                if short_description:
                    break

    return {
        "slug": slug,
        "title": title,
        "short_description": short_description or ("ActionBoard mission: %s" % title),
        "start_date": start_date,
        "end_date": end_date,
    }


def build_plan_markdown(mission_dir):
    """Build the markdown payload for assistprofile_createMissionPlan."""
    parts = []
    brief_path = os.path.join(mission_dir, "mission-brief.md")
    plan_path = os.path.join(mission_dir, "mission-plan.md")
    report_path = os.path.join(mission_dir, "mission-report.md")

    if os.path.exists(brief_path):
        with open(brief_path, encoding="utf-8") as fh:
            parts.append(fh.read().strip())
    if os.path.exists(plan_path):
        with open(plan_path, encoding="utf-8") as fh:
            parts.append(fh.read().strip())
    if not parts and os.path.exists(report_path):
        with open(report_path, encoding="utf-8") as fh:
            parts.append(fh.read().strip())
    return "\n\n---\n\n".join(p for p in parts if p)


def collect_mission_files(mission_dir):
    found = []
    for filename, mime_type, tags, note in MISSION_FILES:
        full = os.path.join(mission_dir, filename)
        if os.path.isfile(full):
            found.append({
                "path": full,
                "fileName": filename,
                "fileType": mime_type or mimetypes.guess_type(filename)[0] or "application/octet-stream",
                "fileSize": os.path.getsize(full),
                "tags": list(tags),
                "note": note,
            })
    return found


# --------------------------------------------------------- Interactive pickers

def prompt_choice(prompt_text, items, label_fn, allow_zero_label=None):
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


def select_pod_and_board(settings, main_token, pod_arg=None, board_arg=None, interactive=True, opener=None):
    cfg = settings["cfg"]
    pods = fetch_my_pods(settings, main_token, opener=opener)
    if not pods:
        fail("your ActionBoard account has no pods.")

    selected_pod = None
    target_pod_id = pod_arg or cfg.get("pod_id")
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
    cfg["pod_name"] = selected_pod.get("podName") or ""
    if pod_hostname:
        cfg["pod_hostname"] = pod_hostname
    cfg["board_id"] = selected_board["boardId"]
    cfg["board_name"] = selected_board.get("name") or ""
    save_config_json(settings["config_file"], cfg)

    return selected_pod, selected_board, pod_id_token


# --------------------------------------------------------- Fallback FileUpload

def fallback_upload_via_filemanager(settings, pod_id_token, board_id, mission_id, mission_title, uploaded_reports, opener=None):
    """If assistprofile_submitReports fails because a legacy mission has no missionFolderId,
    create/find the Mission folder in FileManager and register each file via filemanager_createFile.
    """
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


# --------------------------------------------------------------- Subcommands

def cmd_configure(args):
    cred_file = args.credentials_file or default_credentials_path()
    creds = load_json_file(cred_file)
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
    saved_path = save_secure_json(cred_file, creds)
    info("Saved ActionBoard CLI configuration to %s (mode 0600)." % saved_path)
    return 0


def cmd_login(args, opener=None):
    settings = resolve_settings(args.credentials_file, args.config, args)
    email = args.email or os.environ.get("ACTIONBOARD_EMAIL") or settings["creds"].get("email")
    password = args.password or os.environ.get("ACTIONBOARD_PASSWORD")

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
        "Logged in as %s (profileId: %s). Credentials stored in %s."
        % (creds.get("email"), creds.get("profile_id") or "resolved on pod exchange", settings["cred_file"])
    )
    return 0


def cmd_status(args):
    settings = resolve_settings(args.credentials_file, args.config, args)
    creds = settings["creds"]
    cfg = settings["cfg"]
    aws_creds = resolve_aws_credentials(creds)
    has_token = bool(creds.get("access_token") and token_is_valid(creds.get("access_token")))

    status_obj = {
        "credentials_file": settings["cred_file"],
        "config_file": settings["config_file"],
        "appsync_configured": bool(settings["endpoint"] and settings["api_key"]),
        "appsync_endpoint": settings["endpoint"] or "",
        "logged_in": has_token,
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
    }
    if getattr(args, "json", False):
        info(json.dumps(status_obj, indent=2))
        return 0

    info("ActionBoard CLI Status:")
    info("  Credentials file : %s" % status_obj["credentials_file"])
    info("  AppSync endpoint : %s" % (status_obj["appsync_endpoint"] or "NOT SET"))
    info("  Authenticated    : %s%s" % (
        "yes" if has_token else "no",
        (" (%s, profileId=%s)" % (status_obj["email"], status_obj["profile_id"] or "n/a")) if status_obj["email"] else "",
    ))
    info("  S3 target        : s3://%s/%s (%s) — AWS creds: %s" % (
        status_obj["s3_bucket"],
        status_obj["s3_prefix"],
        status_obj["s3_region"],
        "ready" if status_obj["aws_s3_credentials_ready"] else "missing",
    ))
    info("  Selected Pod     : %s" % (
        ("%s (%s)" % (status_obj["default_pod_name"], status_obj["default_pod_id"]))
        if status_obj["default_pod_id"] else "none"
    ))
    info("  Selected Board   : %s" % (
        ("%s (%s)" % (status_obj["default_board_name"], status_obj["default_board_id"]))
        if status_obj["default_board_id"] else "none"
    ))
    return 0


def cmd_pods(args, opener=None):
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
    settings = resolve_settings(args.credentials_file, args.config, args)
    main_token = ensure_main_token(settings, interactive=not getattr(args, "no_input", False), opener=opener)
    pod_id = args.pod or settings["cfg"].get("pod_id")
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
    settings = resolve_settings(args.credentials_file, args.config, args)
    main_token = ensure_main_token(settings, interactive=not getattr(args, "no_input", False), opener=opener)
    pod_id = args.pod or settings["cfg"].get("pod_id")
    board_id = args.board or settings["cfg"].get("board_id")
    if not pod_id or not board_id:
        fail("pass --pod <podId> and --board <boardId>, or run `python submit_mission.py select` first")
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


def _resolve_pod_token_and_profile(settings, main_token, pod_arg=None, interactive=True, opener=None):
    cfg = settings["cfg"]
    pods = fetch_my_pods(settings, main_token, opener=opener)
    if not pods:
        fail("your ActionBoard account has no pods.")

    selected_pod = None
    target_pod_id = pod_arg or cfg.get("pod_id")
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
    settings = resolve_settings(args.credentials_file, args.config, args)
    interactive = not getattr(args, "no_input", False) and sys.stdin.isatty()
    main_token = ensure_main_token(settings, interactive=interactive, opener=opener)
    pod, pod_id_token, profile_id = _resolve_pod_token_and_profile(
        settings, main_token, pod_arg=args.pod, interactive=interactive, opener=opener
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
    settings = resolve_settings(args.credentials_file, args.config, args)
    interactive = not getattr(args, "no_input", False) and sys.stdin.isatty()
    main_token = ensure_main_token(settings, interactive=interactive, opener=opener)
    pod, pod_id_token, profile_id = _resolve_pod_token_and_profile(
        settings, main_token, pod_arg=args.pod, interactive=interactive, opener=opener
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
                if aws_creds and s3_obj.get("bucket") and s3_obj.get("key"):
                    try:
                        raw_bytes = download_bytes_from_s3(
                            s3_obj["bucket"],
                            s3_obj.get("region") or settings["s3_region"],
                            s3_obj["key"],
                            aws_creds,
                            opener=opener,
                        )
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
    settings = resolve_settings(args.credentials_file, args.config, args)
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
    return 0


def cmd_submit(args, opener=None):
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

    main_token = ensure_main_token(settings, interactive=interactive, opener=opener)
    pod, board, pod_id_token = select_pod_and_board(
        settings,
        main_token,
        pod_arg=args.pod,
        board_arg=args.board,
        interactive=interactive,
        opener=opener,
    )
    pod_id = pod["podId"]
    board_id = board["boardId"]
    profile_id = (
        args.assigned_agent
        or settings["creds"].get("profile_id")
        or decode_jwt_payload(pod_id_token).get("custom:profileId")
        or ""
    )

    cfg = settings["cfg"]
    missions_map = cfg.get("missions") if isinstance(cfg.get("missions"), dict) else {}
    saved_entry = missions_map.get(meta["slug"]) if isinstance(missions_map.get(meta["slug"]), dict) else {}

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

    uploaded_files = []
    if files_to_upload and not args.skip_reports:
        aws_creds = resolve_aws_credentials(settings["creds"])
        timestamp_ms = int(time.time() * 1000)
        reports_input = []

        for item_idx, f in enumerate(files_to_upload):
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
                if not aws_creds:
                    warn(
                        "AWS S3 credentials are not configured; skipping S3 binary upload and "
                        "registering report metadata only. Configure AWS_ACCESS_KEY_ID / "
                        "AWS_SECRET_ACCESS_KEY or pass --aws-access-key-id to `configure` for S3 binary upload."
                    )
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
                "tags": f["tags"] + [mission_id],
            })

        submit_input = {
            "missionId": mission_id,
            "boardId": board_id,
            "reports": reports_input,
        }
        if plan_id:
            submit_input["planId"] = plan_id

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

    missions_map[meta["slug"]] = {
        "mission_id": mission_id,
        "plan_id": plan_id or "",
        "board_id": board_id,
        "pod_id": pod_id,
        "title": title,
        "updated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    cfg["missions"] = missions_map
    save_config_json(settings["config_file"], cfg)

    result_summary = {
        "success": True,
        "pod_id": pod_id,
        "pod_name": pod.get("podName") or "",
        "board_id": board_id,
        "board_name": board.get("name") or "",
        "mission_id": mission_id,
        "created_new_mission": created_new_mission,
        "plan_id": plan_id or "",
        "files_submitted": [f.get("fileName") for f in uploaded_files] or [f["fileName"] for f in files_to_upload],
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
    sp_cfg.add_argument("--cognito-domain", help="Cognito domain URL")
    sp_cfg.add_argument("--cognito-client-id", help="Cognito client ID")
    sp_cfg.add_argument("--aws-access-key-id", help="AWS access key ID for S3 upload")
    sp_cfg.add_argument("--aws-secret-access-key", help="AWS secret access key for S3 upload")
    sp_cfg.add_argument("--aws-session-token", help="AWS session token (optional)")

    sp_login = sub.add_parser("login", parents=[common_sub], help="authenticate with ActionBoard and cache tokens")
    sp_login.add_argument("--email", help="ActionBoard account email")
    sp_login.add_argument("--password", help="ActionBoard account password (prompts if omitted)")

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
    sp_submit.add_argument("--dry-run", action="store_true", help="validate local files and print what would be submitted")
    sp_submit.add_argument("--no-input", action="store_true", help="fail instead of prompting interactively")
    sp_submit.add_argument("--json", action="store_true", help="output JSON summary")

    return p


def main(argv=None, opener=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    dispatch = {
        "configure": lambda: cmd_configure(args),
        "login": lambda: cmd_login(args, opener=opener),
        "status": lambda: cmd_status(args),
        "pods": lambda: cmd_pods(args, opener=opener),
        "boards": lambda: cmd_boards(args, opener=opener),
        "missions": lambda: cmd_missions(args, opener=opener),
        "assigned": lambda: cmd_assigned(args, opener=opener),
        "fetch": lambda: cmd_fetch(args, opener=opener),
        "select": lambda: cmd_select(args, opener=opener),
        "submit": lambda: cmd_submit(args, opener=opener),
    }
    return dispatch[args.subcommand]()


if __name__ == "__main__":
    sys.exit(main())
