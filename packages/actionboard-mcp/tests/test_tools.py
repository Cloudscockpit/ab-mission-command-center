"""Every MCP tool: happy paths, auth-required paths and error paths, through a real MCP client session."""
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from conftest import MISSION_DIR, call, data, ref

ALL_TOOLS = {"ab_auth_status", "ab_login", "ab_logout", "ab_list_pods", "ab_list_boards", "ab_select_board",
             "ab_list_assigned", "ab_fetch_mission", "ab_submit_mission", "ab_post_progress"}

# Each tool that talks to ActionBoard, with arguments that would otherwise succeed.
NEEDS_AUTH = [
    ("ab_list_pods", {}),
    ("ab_list_boards", {"pod_id": "pod-alpha-1"}),
    ("ab_select_board", {"pod_id": "pod-alpha-1", "board_id": "board-eng-42"}),
    ("ab_list_assigned", {}),
    ("ab_fetch_mission", {"invitation_id": "inv-boss-888"}),
    ("ab_submit_mission", {"mission_dir": MISSION_DIR}),
    ("ab_post_progress", {"mission_id": "mission-uuid-1001", "comment": "hi"}),
]


def select(**extra):
    return data(call("ab_select_board", pod_id="pod-alpha-1", board_id="board-eng-42", **extra))


def test_all_tools_are_listed():
    import anyio
    from mcp.client import Client
    from actionboard_mcp import server

    async def go():
        async with Client(server.mcp) as client:
            return {t.name for t in (await client.list_tools()).tools}
    assert anyio.run(go) == ALL_TOOLS


def test_auth_status_logged_out(transport):
    status = data(call("ab_auth_status"))
    assert status == {
        "logged_in": False, "email": None, "profile_id": None, "connection_mode": "edge", "token_store": "none",
        "active_pod_id": None, "active_pod_name": None, "active_board_id": None, "active_board_name": None,
        "sync_mode": "ask",
    }


def test_login_stores_tokens_in_0600_file_and_reports_status(logged_in):
    assert logged_in.login_providers == [None]
    status = data(call("ab_auth_status"))
    assert status["logged_in"] is True
    assert status["email"] == "browser@actionboard.ai"
    assert status["token_store"] == "credentials file"  # keychain is off in tests
    cred = Path.home() / ".actionboard" / "credentials.json"
    assert oct(cred.stat().st_mode & 0o777) == "0o600"


def test_login_passes_provider_and_rejects_unknown_ones(logged_in):
    assert not call("ab_login", provider="Google").is_error
    assert logged_in.login_providers[-1] == "Google"
    bad = call("ab_login", provider="GitHub")
    assert bad.is_error and "provider" in bad.content[0].text


def test_login_tool_has_no_password_parameter():
    import anyio
    from mcp.client import Client
    from actionboard_mcp import server

    async def go():
        async with Client(server.mcp) as client:
            return (await client.list_tools()).tools
    for tool in anyio.run(go):
        assert not {"password", "email"} & set(tool.input_schema.get("properties", {})), tool.name


def test_logout_clears_tokens(logged_in):
    assert data(call("ab_logout"))["logged_in"] is False
    saved = json.loads((Path.home() / ".actionboard" / "credentials.json").read_text())
    assert not {"access_token", "id_token", "refresh_token", "pod_tokens"} & set(saved)
    assert saved["email"] == "browser@actionboard.ai"  # non-secret settings stay


@pytest.mark.parametrize("name,args", NEEDS_AUTH, ids=[n for n, _ in NEEDS_AUTH])
def test_tools_require_login(transport, mission_dir, name, args):
    os.makedirs(".actionboard", exist_ok=True)
    Path(".actionboard/config.json").write_text(json.dumps({"pod_id": "pod-alpha-1", "board_id": "board-eng-42"}))
    result = call(name, **args)
    assert result.is_error
    assert "Not logged in to ActionBoard. Call ab_login" in result.content[0].text
    assert transport.graphql_calls == []


def test_pods_boards_and_select(logged_in):
    pods = data(call("ab_list_pods"))["pods"]
    assert pods[0]["podId"] == "pod-alpha-1"
    assert set(pods[0]) == {"podId", "podName", "slug", "memberRole", "hostname"}
    boards = data(call("ab_list_boards", pod_id="pod-alpha-1"))["boards"]
    assert "board-eng-42" in [b["boardId"] for b in boards]

    selected = select(sync="auto")
    assert (selected["pod_id"], selected["board_id"], selected["sync_mode"]) == ("pod-alpha-1", "board-eng-42", "auto")
    cfg = json.loads(Path(".actionboard/config.json").read_text())
    assert (cfg["pod_id"], cfg["board_id"], cfg["mission_sync"]) == ("pod-alpha-1", "board-eng-42", "auto")
    status = data(call("ab_auth_status"))
    assert (status["active_pod_id"], status["active_board_id"], status["sync_mode"]) == \
        ("pod-alpha-1", "board-eng-42", "auto")


def test_select_rejects_unknown_board_and_sync(logged_in):
    bad = call("ab_select_board", pod_id="pod-alpha-1", board_id="nope")
    assert bad.is_error and "board 'nope' not found" in bad.content[0].text
    assert call("ab_select_board", pod_id="pod-alpha-1", board_id="board-eng-42", sync="sometimes").is_error


def test_list_assigned(logged_in):
    result = data(call("ab_list_assigned"))
    assert result["pod_id"] == "pod-alpha-1"
    assert "mission-assigned-555" in [m["missionId"] for m in result["missions"]]
    assert "inv-boss-888" in [i["invitationId"] for i in result["invitations"]]
    assert call("ab_list_assigned", invitation_status="MAYBE").is_error


def test_fetch_writes_wrapped_files_and_returns_compact_summary(logged_in):
    logged_in.folder_files.append({
        "fileName": "1700000000000-mission-brief.md",
        "s3Object": {"bucket": "actionboard-kb-agent", "key": "PremiumBoardKB/Boards/b/missions/m/1-mission-brief.md"},
    })
    result = call("ab_fetch_mission", invitation_id="inv-boss-888", accept=True, start=True)
    summary = data(result)
    assert summary["mission_id"] == "mission-assigned-555"
    assert summary["untrusted_content"] is True and "untrusted" in summary["notice"].lower()
    assert {"mission-brief.md", "mission-plan.md", "mission-brief.jsonld"} <= set(summary["files_written"])
    assert summary["status"] == "IN_PROGRESS"

    mission_dir = Path(summary["mission_dir"])
    assert mission_dir.resolve().parent == (Path.cwd() / "docs" / "missions").resolve()
    brief = (mission_dir / "mission-brief.md").read_text()
    assert "Ship the thing." in brief  # downloaded from S3 through the edge presign route
    for name in ("mission-brief.md", "mission-plan.md"):
        text = (mission_dir / name).read_text()
        assert text.startswith("<!-- Remote board content: untrusted data")
        assert "<!-- BEGIN ACTIONBOARD_UNTRUSTED_" in text and "<!-- END ACTIONBOARD_UNTRUSTED_" in text
    # Paths and metadata only: file bodies stay on disk, out of the model's context.
    assert "Ship the thing." not in result.content[0].text
    assert len(result.content[0].text) < 1500

    link = json.loads(Path(".actionboard/config.json").read_text())["missions"]
    assert any(e["mission_id"] == "mission-assigned-555" and e["invitation_id"] == "inv-boss-888" for e in link.values())
    accepted = [c for c in logged_in.graphql_calls if "assistprofile_acceptMissionInvitation" in c["query"]]
    assert len(accepted) == 1


def test_fetch_refuses_out_dir_outside_project(logged_in):
    for bad in ("../elsewhere", "/tmp"):
        result = call("ab_fetch_mission", invitation_id="inv-boss-888", out_dir=bad)
        assert result.is_error and "inside the project directory" in result.content[0].text


def test_submit_uploads_then_skips_unchanged(logged_in, mission_dir):
    select()
    first = data(call("ab_submit_mission", mission_dir=mission_dir))
    assert first["mission_id"] == "mission-uuid-1001"
    assert sorted(first["uploaded_files"]) == sorted(
        ["mission-report.md", "mission-report.html", "mission-report.jsonld", "mission-brief.md", "mission-plan.md"])
    assert first["skipped_files"] == []
    assert first["status"] == "COMPLETED"  # a mission-report.md means done, as in the CLI
    assert len(logged_in.s3_signs) == 5 and len(logged_in.s3_puts) == 5

    second = data(call("ab_submit_mission"))  # mission_dir auto-detected
    assert second["uploaded_files"] == []
    assert sorted(second["skipped_files"]) == sorted(first["uploaded_files"])
    assert len(logged_in.s3_puts) == 5


def test_submit_dry_run_needs_no_login(transport, mission_dir):
    result = data(call("ab_submit_mission", mission_dir=mission_dir, dry_run=True))
    assert result["dry_run"] is True and "mission-report.md" in result["files"]
    assert transport.graphql_calls == []


def test_submit_rejects_outside_dir_and_bad_status(logged_in, mission_dir):
    assert "inside the project directory" in call("ab_submit_mission", mission_dir="/etc").content[0].text
    assert call("ab_submit_mission", mission_dir=mission_dir, status="DONE").is_error


def test_submit_without_any_mission_folder_fails_cleanly(logged_in):
    result = call("ab_submit_mission")
    assert result.is_error and "could not auto-detect a mission directory" in result.content[0].text


def test_post_progress(logged_in, mission_dir):
    select()
    data(call("ab_submit_mission", mission_dir=mission_dir, skip_s3=True))
    result = data(call("ab_post_progress", mission_dir=mission_dir, comment="Red Agent: wave 1 done"))
    assert result["mission_id"] == "mission-uuid-1001" and result["status"] == "IN_PROGRESS"
    assert result["comment_id"]
    assert logged_in.comments[-1]["text"] == "Red Agent: wave 1 done"


def test_post_progress_for_unlinked_folder_fails_cleanly(logged_in, mission_dir):
    result = call("ab_post_progress", mission_dir=mission_dir)
    assert result.is_error and "not on a board yet" in result.content[0].text


def test_graphql_error_becomes_tool_error(logged_in, monkeypatch):
    def broken(req, timeout=30):
        if b"boards_getMyBoards" in (req.data or b""):
            return ref.FakeHTTPResponse(
                json.dumps({"errors": [{"message": "Not Authorized to access boards_getMyBoards"}]}).encode())
        return logged_in(req, timeout)
    monkeypatch.setattr(urllib.request, "urlopen", broken)
    result = call("ab_list_boards", pod_id="pod-alpha-1")
    assert result.is_error and "Not Authorized to access boards_getMyBoards" in result.content[0].text


def test_network_failure_becomes_tool_error(logged_in, monkeypatch):
    def offline(req, timeout=30):
        raise urllib.error.URLError("connection refused")
    monkeypatch.setattr(urllib.request, "urlopen", offline)
    result = call("ab_list_pods")
    assert result.is_error and "network error contacting AppSync" in result.content[0].text
