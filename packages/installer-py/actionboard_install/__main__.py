"""ActionBoard zero-clone installer (uvx flavour). Standard library only.

Downloads the release bundle to a temp dir, runs scripts/install.py from it
with a PERSISTENT Python interpreter (never the ephemeral uvx environment,
because the interpreter path is baked into installed hook commands), then
removes the temp dir.
"""
import argparse
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from urllib.parse import urlparse

VERSION = "1.1.0"
REPO = "Cloudscockpit/ab-mission-command-center"
TARGETS = ("codex", "antigravity", "opencode")
MAX_REDIRECTS = 5

PROBE = (
    "import sys; print(sys.version_info[:2] >= (3,9)); "
    "print(sys.executable); print(sys.prefix)"
)

PY_HINT = (
    "Python 3.9+ was not found. Install it from https://www.python.org/downloads/ "
    "or set ACTIONBOARD_PYTHON to a Python 3.9+ executable. "
    'Note: the Microsoft Store "python" stub does not count.'
)


class InstallerError(Exception):
    pass


def build_parser():
    ap = argparse.ArgumentParser(
        prog="actionboard-install",
        description="Install ActionBoard for Codex, Antigravity or OpenCode.",
        epilog="Env: ACTIONBOARD_BUNDLE (local .tar.gz or https URL), "
               "ACTIONBOARD_PYTHON (persistent python executable). "
               "Claude Code: /plugin marketplace add " + REPO,
    )
    ap.add_argument("--target", required=True)
    ap.add_argument("--global", dest="glob", action="store_true")
    ap.add_argument("--project")
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--with", dest="with_")
    ap.add_argument("--without")
    ap.add_argument("--version", action="version", version=VERSION)
    return ap


def parse_args(argv, cwd=None):
    ap = build_parser()
    a = ap.parse_args(argv)
    if a.target == "claude":
        ap.error("Claude Code is installed as a plugin. Run: /plugin marketplace add " + REPO)
    if a.target not in TARGETS:
        ap.error("invalid --target %r (allowed: %s)" % (a.target, ", ".join(TARGETS)))
    if a.glob and a.project:
        ap.error("--global and --project are mutually exclusive")
    a.project_abs = os.path.abspath(os.path.join(cwd or os.getcwd(), a.project or "."))
    return a


def build_install_args(a):
    out = ["--target", a.target]
    out += ["--global"] if a.glob else ["--project", a.project_abs]
    if a.uninstall:
        out.append("--uninstall")
    if a.dry_run:
        out.append("--dry-run")
    if a.yes:
        out.append("--yes")
    if a.force:
        out.append("--force")
    if a.with_:
        out += ["--with", a.with_]
    if a.without:
        out += ["--without", a.without]
    return out


def _norm(p):
    return os.path.normcase(os.path.realpath(p))


def _under(path, root):
    path, root = _norm(path), _norm(root)
    return path == root or path.startswith(root + os.sep)


def _uv_cache_dirs():
    dirs = []
    if os.environ.get("UV_CACHE_DIR"):
        dirs.append(os.environ["UV_CACHE_DIR"])
    for var, sub in (("LOCALAPPDATA", "uv"), ("XDG_CACHE_HOME", "uv")):
        if os.environ.get(var):
            dirs.append(os.path.join(os.environ[var], sub))
    dirs.append(os.path.join(os.path.expanduser("~"), ".cache", "uv"))
    return dirs


def _is_ephemeral(exe, prefix):
    """True if this interpreter lives in uv's cache or in the current (uvx) env."""
    for d in _uv_cache_dirs():
        if _under(exe, d) or _under(prefix, d):
            return True
    parts = {p.lower() for p in _norm(exe).replace("\\", "/").split("/")}
    if any(p.startswith(("archive-v", "builds-v", "environments-v")) for p in parts):
        return True
    if sys.prefix != getattr(sys, "base_prefix", sys.prefix):
        if _under(exe, sys.prefix) or _under(prefix, sys.prefix):
            return True
    return False


def _probe(cmd, run=subprocess.run):
    try:
        r = run(cmd + ["-I", "-c", PROBE], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    lines = [s.strip() for s in (r.stdout or "").splitlines() if s.strip()]
    if len(lines) < 3 or lines[0] != "True":
        return None
    return lines[1], lines[2]


def resolve_python(env=None, which=shutil.which, run=subprocess.run):
    """Return (executable, warning_or_None) for a persistent Python 3.9+."""
    env = os.environ if env is None else env
    forced = env.get("ACTIONBOARD_PYTHON")
    if forced:
        p = _probe([forced], run)
        if not p:
            raise InstallerError("ACTIONBOARD_PYTHON=%s is not a working Python 3.9+" % forced)
        return p[0], None
    cands = []
    for name, extra in (("py", ["-3"]), ("python3", []), ("python", [])):
        found = which(name)
        if found:
            cands.append([found] + extra)
    for cmd in cands:
        p = _probe(cmd, run)
        if p and not _is_ephemeral(*p):
            return p[0], None
    base = getattr(sys, "_base_executable", None)
    if base and sys.version_info >= (3, 9) and os.path.exists(base):
        return base, ("no persistent Python found on PATH; falling back to %s. "
                      "Installed hooks will reference it." % base)
    raise InstallerError(PY_HINT)


def download(url, dest, redirects=0, opener=None):
    u = urlparse(url)
    if u.scheme != "https":
        raise InstallerError("refusing non-https URL: " + url)

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None

    op = opener or urllib.request.build_opener(NoRedirect)
    req = urllib.request.Request(url, headers={"User-Agent": "actionboard-install/" + VERSION})
    try:
        with op.open(req, timeout=60) as resp, open(dest, "wb") as out:
            shutil.copyfileobj(resp, out)
        return
    except urllib.error.HTTPError as e:
        e.close()
        if 300 <= e.code < 400 and e.headers.get("Location"):
            if redirects >= MAX_REDIRECTS:
                raise InstallerError("too many redirects")
            nxt = urllib.parse.urljoin(url, e.headers["Location"])
            return download(nxt, dest, redirects + 1, opener)
        if e.code == 404:
            raise InstallerError("release v%s not found - tag not published yet (%s)" % (VERSION, url))
        raise InstallerError("download failed: HTTP %s for %s" % (e.code, url))
    except urllib.error.URLError as e:
        raise InstallerError("download failed: %s" % e.reason)


def safe_extract(archive, dest):
    with tarfile.open(archive) as t:
        if hasattr(tarfile, "data_filter"):
            t.extractall(dest, filter="data")
            return
        root = os.path.realpath(dest)

        def inside(p):
            return p == root or p.startswith(root + os.sep)

        for m in t.getmembers():
            n = m.name.replace("\\", "/")
            if os.path.isabs(m.name) or n.startswith("/") or ".." in n.split("/"):
                raise InstallerError("unsafe archive member: " + m.name)
            if not inside(os.path.realpath(os.path.join(dest, m.name))):
                raise InstallerError("unsafe archive member: " + m.name)
            if m.issym() or m.islnk() or m.isdev():
                raise InstallerError("links and special files are not allowed: " + m.name)
        t.extractall(dest)


def find_top(d):
    ents = os.listdir(d)
    if len(ents) != 1 or not os.path.isdir(os.path.join(d, ents[0])):
        raise InstallerError("bundle must contain exactly one top-level directory")
    return os.path.join(d, ents[0])


def run(argv=None):
    a = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        py, warn = resolve_python()
        if warn:
            print("warning: " + warn, file=sys.stderr)
        # TemporaryDirectory cleans up on normal exit and on exceptions
        # (including KeyboardInterrupt); SIGTERM is converted below.
        with tempfile.TemporaryDirectory(prefix="actionboard-install-") as tmp:
            src = os.environ.get("ACTIONBOARD_BUNDLE") or (
                "https://codeload.github.com/%s/tar.gz/refs/tags/v%s" % (REPO, VERSION))
            if src.lower().startswith(("http://", "https://")):
                archive = os.path.join(tmp, "bundle.tar.gz")
                download(src, archive)
            else:
                archive = os.path.abspath(src)
                if not os.path.isfile(archive):
                    raise InstallerError("bundle not found: " + archive)
            ex = os.path.join(tmp, "src")
            os.mkdir(ex)
            try:
                safe_extract(archive, ex)
            except (tarfile.TarError, OSError) as e:
                raise InstallerError("failed to extract bundle: %s" % e)
            script = os.path.join(find_top(ex), "scripts", "install.py")
            if not os.path.isfile(script):
                raise InstallerError("bundle does not contain scripts/install.py")
            cwd = os.path.expanduser("~") if a.glob else a.project_abs
            os.makedirs(cwd, exist_ok=True)
            return subprocess.call([py, script] + build_install_args(a), cwd=cwd)
    except InstallerError as e:
        print("error: %s" % e, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


def main():
    import signal

    def _term(signum, frame):
        raise KeyboardInterrupt

    try:
        signal.signal(signal.SIGTERM, _term)
    except (ValueError, OSError):
        pass
    sys.exit(run())


if __name__ == "__main__":
    main()
