"""ActionBoard CLI: common."""
import json
import os
import stat
import sys
import tempfile


DEFAULT_S3_REGION = "ap-southeast-1"


DEFAULT_S3_BUCKET = "actionboard-kb-agent"


DEFAULT_S3_PREFIX = "PremiumBoardKB/Boards/Investor+Boards"


DEFAULT_COGNITO_DOMAIN = "https://absaas-dev.auth.ap-southeast-1.amazoncognito.com/"


DEFAULT_EDGE_PROXY_URL = "https://actionboard-edge-proxy.ab-mobile.workers.dev"


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


_EDGE_CONTEXT = {}


