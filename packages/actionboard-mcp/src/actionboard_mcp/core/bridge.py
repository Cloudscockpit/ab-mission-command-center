"""Runs the vendored ActionBoard CLI handlers safely inside a server or a library call.

The CLI's `fail()` calls `sys.exit()` and `info()` writes to stdout. Both would break an MCP stdio
server, so `install()` swaps them on `actionboard_cli.common`. Every CLI module imports them from
there at call time, so the swap reaches all callers without editing the vendored code.
"""
import json
import re
import sys
import threading

from ..actionboard_cli import common

CONFIG_PATH = ".actionboard/config.json"

_SECRET_KEY = re.compile(r"(^|_)(access|id|refresh|pod|session)_?tokens?$|^tokens?$|secret|password|api_?key|"
                         r"authorization|cookie|verifier", re.I)
_JWT = re.compile(r"eyJ[A-Za-z0-9_-]{5,}(?:\.[A-Za-z0-9_-]*){1,4}")
_SECRET_FIELDS = ("access_token", "id_token", "refresh_token", "appsync_api_key", "aws_secret_access_key",
                  "aws_session_token", "aws_access_key_id")
REDACTED = "[REDACTED]"

# The CLI keeps per-call state in module globals (_EDGE_CONTEXT), and MCP runs sync tools on worker
# threads, so calls are serialized.
_lock = threading.RLock()
_captured = []
_warnings = []


class ActionBoardError(Exception):
    """A CLI failure, raised instead of sys.exit(). The message is already redacted."""


class AuthRequiredError(ActionBoardError):
    pass


class _Abort(BaseException):
    """What fail() raises: a BaseException like SystemExit, so the CLI's `except Exception` blocks
    still let it through exactly as they let sys.exit() through."""


def _fail(message, code=2):
    raise _Abort(" ".join(str(message).split()))


def _info(message):
    text = str(message)
    _captured.append(text)
    if not text.lstrip().startswith(("{", "[")):  # progress lines (e.g. the sign-in URL) stay visible on stderr
        sys.stderr.write("actionboard: %s\n" % redact(text))


def _warn(message):
    text = redact(str(message))
    _warnings.append(text)
    sys.stderr.write("actionboard: WARNING: %s\n" % text)


def install():
    common.fail, common.info, common.warn = _fail, _info, _warn


def _known_secrets():
    creds = (common._EDGE_CONTEXT.get("settings") or {}).get("creds") or {}
    values = [creds.get(k) for k in _SECRET_FIELDS]
    for pod in (creds.get("pod_tokens") or {}).values():
        values += [(pod or {}).get("id_token"), (pod or {}).get("access_token")]
    return [v for v in values if isinstance(v, str) and len(v) >= 8]


def redact(value, secrets=None):
    """Drop secret-named keys, JWT-shaped strings, and any stored credential value from a result."""
    secrets = _known_secrets() if secrets is None else secrets
    if isinstance(value, dict):
        return {k: (REDACTED if _SECRET_KEY.search(str(k)) else redact(v, secrets)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v, secrets) for v in value]
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, REDACTED)
        return _JWT.sub(REDACTED, value)
    return value


def run(fn, *args, **kwargs):
    """Call a CLI handler; return (last JSON value it printed or None, its return value, warnings)."""
    with _lock:
        install()
        del _captured[:], _warnings[:]
        try:
            result = fn(*args, **kwargs)
        except _Abort as exc:
            text = str(exc)
            if "not logged in" in text:
                raise AuthRequiredError("Not logged in to ActionBoard. Call ab_login (or run `ab login`) first.") from None
            raise ActionBoardError(redact(text)) from None
        except RuntimeError as exc:  # AppSync GraphQL errors, as the CLI's main() reports them
            raise ActionBoardError(redact(str(exc))) from None
        except SystemExit as exc:  # nothing should exit the host process
            raise ActionBoardError("ActionBoard CLI exited unexpectedly (code %s)" % exc.code) from None
        printed = None
        for line in reversed(_captured):
            try:
                printed = json.loads(line)
                break
            except ValueError:
                continue
        return printed, result, list(_warnings)
