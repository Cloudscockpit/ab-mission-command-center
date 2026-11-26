"""OS keychain storage for ActionBoard CLI secrets (standard library only).

Tokens and keys go to the macOS Keychain (`security`), the Windows Credential Manager
(advapi32 via ctypes), or the Linux Secret Service (`secret-tool`). The credentials file then
keeps only non-secret settings plus a `keychain_account` pointer. When no keychain is usable the
secrets stay in the 0600 credentials file, as before. Set ACTIONBOARD_KEYCHAIN=off to force file
storage.

Values are base64 JSON split into chunks of CHUNK_SIZE characters: Windows caps one credential at
2560 bytes and `security -i` truncates input lines at 4096 characters. Secrets never appear on a
command line, only on stdin.
"""
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys

SERVICE = "actionboard-cli"
CHUNK_SIZE = 2400
MAX_CHUNKS = 64  # shortcut: caps one secret at ~150 KB; credentials are a few KB
SECRET_KEYS = (
    "access_token",
    "id_token",
    "refresh_token",
    "pod_tokens",
    "appsync_api_key",
    "aws_secret_access_key",
    "aws_session_token",
)
_TIMEOUT = 20


def backend_name():
    mode = os.environ.get("ACTIONBOARD_KEYCHAIN", "auto").strip().lower()
    if mode in ("off", "0", "false", "no", "file"):
        return None
    if sys.platform == "darwin" and shutil.which("security"):
        return "macos"
    if sys.platform == "win32":
        return "windows"
    if sys.platform.startswith("linux") and shutil.which("secret-tool") and os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        return "secret-service"
    return None


def describe(backend):
    return {
        "macos": "macOS Keychain",
        "windows": "Windows Credential Manager",
        "secret-service": "Linux Secret Service",
    }.get(backend, "credentials file")


def account_for(path):
    """One keychain account per credentials file, so separate files never share secrets."""
    return "creds-" + hashlib.sha256(os.path.abspath(path).encode("utf-8")).hexdigest()[:16]


# ------------------------------------------------------------------ backends
# Each backend stores small ASCII strings under a name and returns None for a missing item.

def _run(cmd, stdin=None):
    return subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=_TIMEOUT)


def _macos_set(name, value):
    line = 'add-generic-password -U -s %s -a %s -l "ActionBoard CLI" -w %s\n' % (SERVICE, name, value)
    _run(["security", "-i"], stdin=line)


def _macos_get(name):
    r = _run(["security", "find-generic-password", "-s", SERVICE, "-a", name, "-w"])
    return r.stdout.strip() if r.returncode == 0 else None


def _macos_delete(name):
    return _run(["security", "delete-generic-password", "-s", SERVICE, "-a", name]).returncode == 0


def _secret_tool_set(name, value):
    _run(["secret-tool", "store", "--label=ActionBoard CLI", "service", SERVICE, "account", name], stdin=value)


def _secret_tool_get(name):
    r = _run(["secret-tool", "lookup", "service", SERVICE, "account", name])
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None


def _secret_tool_delete(name):
    existed = _secret_tool_get(name) is not None
    _run(["secret-tool", "clear", "service", SERVICE, "account", name])
    return existed


def _win():
    import ctypes
    from ctypes import wintypes

    class CREDENTIAL(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", wintypes.FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi32.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(CREDENTIAL))]
    advapi32.CredWriteW.argtypes = [ctypes.POINTER(CREDENTIAL), wintypes.DWORD]
    advapi32.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    advapi32.CredFree.argtypes = [ctypes.c_void_p]
    return ctypes, CREDENTIAL, advapi32


_CRED_TYPE_GENERIC = 1
_CRED_PERSIST_LOCAL_MACHINE = 2


def _windows_target(name):
    return "%s/%s" % (SERVICE, name)


def _windows_set(name, value):
    ctypes, CREDENTIAL, advapi32 = _win()
    blob = value.encode("ascii")
    buf = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
    cred = CREDENTIAL()
    cred.Type = _CRED_TYPE_GENERIC
    cred.TargetName = _windows_target(name)
    cred.UserName = "actionboard"
    cred.CredentialBlobSize = len(blob)
    cred.CredentialBlob = ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte))
    cred.Persist = _CRED_PERSIST_LOCAL_MACHINE
    if not advapi32.CredWriteW(ctypes.byref(cred), 0):
        raise OSError(ctypes.get_last_error(), "CredWriteW failed")


def _windows_get(name):
    ctypes, CREDENTIAL, advapi32 = _win()
    pcred = ctypes.POINTER(CREDENTIAL)()
    if not advapi32.CredReadW(_windows_target(name), _CRED_TYPE_GENERIC, 0, ctypes.byref(pcred)):
        return None
    try:
        size = pcred.contents.CredentialBlobSize
        return bytes(pcred.contents.CredentialBlob[:size]).decode("ascii")
    finally:
        advapi32.CredFree(pcred)


def _windows_delete(name):
    _ctypes, _cred, advapi32 = _win()
    return bool(advapi32.CredDeleteW(_windows_target(name), _CRED_TYPE_GENERIC, 0))


_BACKENDS = {
    "macos": (_macos_set, _macos_get, _macos_delete),
    "windows": (_windows_set, _windows_get, _windows_delete),
    "secret-service": (_secret_tool_set, _secret_tool_get, _secret_tool_delete),
}


# ------------------------------------------------------------------ chunked secret store

def _chunk_name(account, index):
    return "%s.%d" % (account, index)


def delete_secret(account, backend):
    _set, _get, delete = _BACKENDS[backend]
    for index in range(MAX_CHUNKS):
        if not delete(_chunk_name(account, index)):
            break


def write_secret(account, data, backend):
    """Store a JSON-able dict. Returns True only when it reads back identically."""
    set_item, get_item, delete = _BACKENDS[backend]
    encoded = base64.b64encode(json.dumps(data, sort_keys=True).encode("utf-8")).decode("ascii")
    chunks = [encoded[i:i + CHUNK_SIZE] for i in range(0, len(encoded), CHUNK_SIZE)] or [""]
    if len(chunks) > MAX_CHUNKS:
        return False
    try:
        for index, chunk in enumerate(chunks):
            set_item(_chunk_name(account, index), chunk)
        for index in range(len(chunks), MAX_CHUNKS):  # drop leftovers from a longer earlier value
            if not delete(_chunk_name(account, index)):
                break
        return read_secret(account, backend) == json.loads(json.dumps(data, sort_keys=True))
    except (OSError, subprocess.SubprocessError, ValueError):
        return False


def read_secret(account, backend):
    """Return the stored dict, or None when it is missing, unreadable, or corrupt."""
    _set, get_item, _delete = _BACKENDS[backend]
    parts = []
    try:
        for index in range(MAX_CHUNKS):
            chunk = get_item(_chunk_name(account, index))
            if chunk is None:
                break
            parts.append(chunk)
        if not parts:
            return None
        data = json.loads(base64.b64decode("".join(parts)).decode("utf-8"))
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return data if isinstance(data, dict) else None


# ------------------------------------------------------------------ credentials file integration

def split_for_storage(path, creds):
    """Return what to write to the credentials file, moving secrets to the keychain when possible."""
    backend = backend_name()
    secrets = {k: creds[k] for k in SECRET_KEYS if creds.get(k) not in (None, "", {})}
    public = {k: v for k, v in creds.items() if k not in SECRET_KEYS and k not in ("keychain_account", "keychain_backend")}
    previous_account = creds.get("keychain_account")
    previous_backend = creds.get("keychain_backend")
    if backend and secrets:
        account = previous_account or account_for(path)
        if write_secret(account, secrets, backend):
            public["keychain_account"] = account
            public["keychain_backend"] = backend
            return public
        sys.stderr.write("submit_mission: WARNING: could not save tokens to the %s; keeping them in %s (mode 0600).\n"
                         % (describe(backend), path))
    if previous_account and previous_backend in _BACKENDS:
        try:
            delete_secret(previous_account, previous_backend)  # the file is now the only copy
        except (OSError, subprocess.SubprocessError):
            pass
    return dict(public, **secrets)


def merge_from_keychain(creds):
    """Fill secrets back in from the keychain item the credentials file points to."""
    account = creds.get("keychain_account")
    backend = creds.get("keychain_backend")
    if not account or backend not in _BACKENDS:
        return creds
    secrets = read_secret(account, backend)
    if secrets is None:
        sys.stderr.write("submit_mission: WARNING: tokens not found in the %s; log in again.\n" % describe(backend))
        return creds
    merged = dict(creds)
    for key in SECRET_KEYS:
        if key in secrets:
            merged[key] = secrets[key]
    return merged
