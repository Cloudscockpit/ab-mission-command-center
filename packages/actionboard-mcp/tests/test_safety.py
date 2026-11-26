"""Proofs the MCP layer never exits, never writes to stdout, and never leaks tokens; plus CLI and vendor checks."""
import filecmp
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from actionboard_mcp import cli
from actionboard_mcp._vendor.actionboard_cli import auth
from actionboard_mcp.core import bridge
from conftest import MISSION_DIR, REPO, call, data, ref

FAILING_CALLS = [
    ("ab_auth_status", {}),
    ("ab_login", {}),
    ("ab_logout", {}),
    ("ab_list_pods", {}),
    ("ab_list_boards", {"pod_id": "pod-alpha-1"}),
    ("ab_select_board", {"pod_id": "pod-alpha-1", "board_id": "board-eng-42"}),
    ("ab_list_assigned", {}),
    ("ab_fetch_mission", {"invitation_id": "inv-boss-888"}),
    ("ab_submit_mission", {"mission_dir": MISSION_DIR}),
    ("ab_post_progress", {"mission_id": "mission-uuid-1001", "comment": "x"}),
]


@pytest.fixture
def exits(monkeypatch):
    """Record every sys.exit (still raising SystemExit, as the real one does)."""
    calls = []

    def tripwire(code=0):
        calls.append(code)
        raise SystemExit(code)
    monkeypatch.setattr(sys, "exit", tripwire)
    return calls


@pytest.mark.parametrize("offline", [False, True], ids=["logged-out", "network-down"])
def test_failing_tools_never_exit_or_write_stdout(transport, mission_dir, monkeypatch, capfd, exits, offline):
    Path(".actionboard").mkdir()
    Path(".actionboard/config.json").write_text(json.dumps({"pod_id": "pod-alpha-1", "board_id": "board-eng-42"}))
    monkeypatch.setattr(auth, "login_with_browser",
                        lambda *a, **k: bridge.common.fail("browser login timed out after 300 seconds"))
    if offline:
        monkeypatch.setenv("ACTIONBOARD_ACCESS_TOKEN", transport.main_access_token)

        def down(req, timeout=30):
            raise urllib.error.URLError("connection refused")
        monkeypatch.setattr(urllib.request, "urlopen", down)

    failed = []
    for name, args in FAILING_CALLS:
        result = call(name, **args)
        if result.is_error:
            failed.append(name)
    assert exits == []
    assert capfd.readouterr().out == ""
    # Status and logout work offline; every other tool reports a clean error.
    assert set(failed) == {n for n, _ in FAILING_CALLS} - {"ab_auth_status", "ab_logout"}


def test_successful_tools_never_write_stdout_or_exit(logged_in, mission_dir, capfd, exits):
    data(call("ab_list_pods"))
    data(call("ab_select_board", pod_id="pod-alpha-1", board_id="board-eng-42"))
    data(call("ab_fetch_mission", invitation_id="inv-boss-888"))
    data(call("ab_submit_mission", mission_dir=mission_dir))
    data(call("ab_post_progress", mission_dir=mission_dir, comment="ok"))
    assert exits == []
    assert capfd.readouterr().out == ""


def test_tokens_never_appear_in_any_tool_output(logged_in, mission_dir):
    outputs = [
        call("ab_auth_status"), call("ab_list_pods"), call("ab_list_boards", pod_id="pod-alpha-1"),
        call("ab_select_board", pod_id="pod-alpha-1", board_id="board-eng-42"), call("ab_list_assigned"),
        call("ab_fetch_mission", invitation_id="inv-boss-888"), call("ab_submit_mission", mission_dir=mission_dir),
        call("ab_post_progress", mission_dir=mission_dir, comment="ok"), call("ab_login"), call("ab_logout"),
    ]
    stored = json.loads((Path.home() / ".actionboard" / "credentials.json").read_text())
    assert stored["email"]  # tokens were really stored and used during the run
    for result in outputs:
        text = result.content[0].text + json.dumps(result.structured_content or {})
        for secret in logged_in.secrets():
            assert secret not in text
        assert "eyJ" not in text


def test_tokens_are_redacted_from_error_messages(logged_in, monkeypatch):
    def echo(req, timeout=30):
        if b"boards_getMyBoards" in (req.data or b""):
            leak = "bad token %s / %s" % (req.get_header("Authorization"), "refresh-from-browser")
            return ref.FakeHTTPResponse(json.dumps({"errors": [{"message": leak}]}).encode())
        return logged_in(req, timeout)
    monkeypatch.setattr(urllib.request, "urlopen", echo)
    text = call("ab_list_boards", pod_id="pod-alpha-1").content[0].text
    assert "bad token" in text and bridge.REDACTED in text
    for secret in logged_in.secrets():
        assert secret not in text


def test_redact_unit():
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2ln"
    out = bridge.redact({
        "accessToken": "a", "id_token": "b", "pod_tokens": {"p": {"id_token": "c"}}, "appsync_api_key": "d",
        "token_store": "macOS Keychain", "note": "Bearer %s" % jwt, "nested": ["opaque-secret-123"],
    }, secrets=["opaque-secret-123"])
    assert out == {
        "accessToken": "[REDACTED]", "id_token": "[REDACTED]", "pod_tokens": "[REDACTED]",
        "appsync_api_key": "[REDACTED]", "token_store": "macOS Keychain", "note": "Bearer [REDACTED]",
        "nested": ["[REDACTED]"],
    }


def test_stdio_server_emits_only_jsonrpc(transport, tmp_path):
    """Real subprocess over stdio: every stdout line must be a JSON-RPC message."""
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "SYSTEMROOT", "PYTHONPATH")}
    env.update(HOME=str(tmp_path), ACTIONBOARD_KEYCHAIN="off", ACTIONBOARD_EDGE_PROXY_URL="http://127.0.0.1:9")
    proc = subprocess.Popen([sys.executable, "-m", "actionboard_mcp.server", "--project-dir", os.getcwd()],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, text=True)
    lines = []

    def send(msg, expect_reply=True):
        proc.stdin.write(json.dumps(msg) + "\n")
        proc.stdin.flush()
        if expect_reply:
            lines.append(proc.stdout.readline())
    try:
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}})
        send({"jsonrpc": "2.0", "method": "notifications/initialized"}, expect_reply=False)
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "ab_auth_status", "arguments": {}}})
        send({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "ab_list_pods", "arguments": {}}})
    finally:
        rest, _err = proc.communicate(timeout=30)  # closes stdin, so the server exits
    lines += [line for line in rest.splitlines() if line]
    messages = [json.loads(line) for line in lines]  # raises on any stray non-JSON output
    assert all(m.get("jsonrpc") == "2.0" for m in messages)
    by_id = {m.get("id"): m for m in messages}
    assert by_id[2]["result"]["isError"] is False
    assert by_id[3]["result"]["isError"] is True
    assert "Not logged in" in by_id[3]["result"]["content"][0]["text"]


def test_cli_prints_json_and_uses_exit_codes(transport, mission_dir, capsys):
    assert cli.main(["status"]) == 0
    assert json.loads(capsys.readouterr().out)["logged_in"] is False
    assert cli.main(["submit", "--mission-dir", mission_dir, "--dry-run"]) == 0
    assert "mission-plan.md" in json.loads(capsys.readouterr().out)["files"]
    assert cli.main(["pods"]) == 3
    out = capsys.readouterr()
    assert out.out == "" and "Not logged in" in out.err


def test_vendored_cli_matches_repo_source():
    source = REPO / "src" / "skills" / "mission-report" / "scripts" / "actionboard_cli"
    vendored = Path(__file__).resolve().parents[1] / "src" / "actionboard_mcp" / "_vendor" / "actionboard_cli"
    names = sorted(p.name for p in source.glob("*.py"))
    assert names == sorted(p.name for p in vendored.glob("*.py"))
    _match, mismatch, errors = filecmp.cmpfiles(source, vendored, names, shallow=False)
    assert not mismatch and not errors, "vendored actionboard_cli drifted; resync it (see README): %s" % mismatch
