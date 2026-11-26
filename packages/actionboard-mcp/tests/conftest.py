"""Fixtures: an isolated project dir and HOME, and the CLI's reference mock of AppSync/edge/S3 behind urlopen."""
import importlib.util
import json
import os
import urllib.request
from pathlib import Path

import anyio
import pytest
from mcp.client import Client

REPO = Path(__file__).resolve().parents[3]
REFERENCE = REPO / "tests" / "report" / "test_submit_mission.py"

if not REFERENCE.exists():  # the package was copied out of the repo
    pytest.skip("reference mock transport not found", allow_module_level=True)
_spec = importlib.util.spec_from_file_location("ab_reference_tests", REFERENCE)
ref = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ref)

from actionboard_mcp import server  # noqa: E402
from actionboard_mcp._vendor.actionboard_cli import auth  # noqa: E402

MISSION_DIR = "docs/missions/2026-11-13-cli-mission-upload"


class EdgeTransport(ref.MockActionBoardTransport):
    """Adds the edge proxy's presign route and S3 GETs, as the reference edge-mode test does."""

    def __init__(self):
        super().__init__()
        self.s3_signs = []

    def __call__(self, req, timeout=30):
        url = req.full_url
        if url.endswith("/s3/sign"):
            body = json.loads(req.data.decode("utf-8"))
            self.s3_signs.append(body)
            signed = "https://%s.s3.ap-southeast-1.amazonaws.com/%s?X-Amz-Signature=x" % (body["bucket"], body["key"])
            return ref.FakeHTTPResponse(json.dumps({"url": signed, "region": "ap-southeast-1"}).encode("utf-8"))
        if req.get_method() == "GET" and ".s3." in url:
            return ref.FakeHTTPResponse(b"# Mission Brief from S3\n\nShip the thing.\n")
        return super().__call__(req, timeout=timeout)

    def secrets(self):
        return [self.main_access_token, self.main_id_token, self.pod_id_token, "refresh-from-browser"]


@pytest.fixture
def transport(tmp_path, monkeypatch):
    for key in list(os.environ):
        if key.startswith(("ACTIONBOARD_", "APPSYNC_", "AWS_", "COGNITO_", "S3_")):
            monkeypatch.delenv(key)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("ACTIONBOARD_KEYCHAIN", "off")  # never touch the developer's real keychain
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "no-aws-credentials"))
    (tmp_path / "project").mkdir()
    monkeypatch.chdir(tmp_path / "project")
    t = EdgeTransport()
    monkeypatch.setattr(urllib.request, "urlopen", t)
    return t


@pytest.fixture
def logged_in(transport, monkeypatch):
    """Replace only the browser round trip; token storage runs for real."""
    calls = []

    def fake_browser_login(settings, provider=None, timeout=300, **_kw):
        calls.append(provider)
        return auth.store_auth_result(settings, {"data": {
            "tokens": {"accessToken": transport.main_access_token, "idToken": transport.main_id_token,
                       "refreshToken": "refresh-from-browser", "expiresIn": 3600},
            "user": {"profileId": "prof-agent-007", "userId": "user-main-1", "email": "browser@actionboard.ai"},
        }})

    monkeypatch.setattr(auth, "login_with_browser", fake_browser_login)
    result = call("ab_login")
    assert not result.is_error, result.content[0].text
    transport.login_providers = calls
    return transport


@pytest.fixture
def mission_dir(transport):
    path = Path(MISSION_DIR)
    path.mkdir(parents=True)
    (path / "mission-brief.md").write_text("# Mission Brief: CLI Mission Upload\n\n## Objective\nSubmit docs.\n")
    (path / "mission-plan.md").write_text("# Mission Plan — CLI Mission Upload\n\n## Wave 1\nBuild it.\n")
    (path / "mission-report.md").write_text("# Mission Report — CLI Mission Upload\n\nDone.\n")
    (path / "mission-report.html").write_text("<!doctype html><html><body>Dashboard</body></html>\n")
    (path / "mission-report.jsonld").write_text(json.dumps({"@context": "https://schema.org", "@graph": [
        {"@id": "urn:voltron:mission:cli-mission-upload", "@type": "Project", "name": "CLI Mission Upload"}]}))
    return MISSION_DIR


def call(name, **arguments):
    """Call a tool through a real in-process MCP client session."""
    async def go():
        async with Client(server.mcp) as client:
            return await client.call_tool(name, arguments)
    return anyio.run(go)


def data(result):
    assert not result.is_error, result.content[0].text
    return json.loads(result.content[0].text)
