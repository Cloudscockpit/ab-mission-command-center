"""Pod services CLI (actionlist, action, goal, files): mocked transport, no network, no keychain."""
import ast
import base64
import contextlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS_DIR = os.path.join(ROOT, "src", "skills", "mission-report", "scripts")
sys.path.insert(0, SCRIPTS_DIR)
os.environ["ACTIONBOARD_KEYCHAIN"] = "off"

import submit_mission  # noqa: E402
from actionboard_cli import operations, pod_commands, pod_services  # noqa: E402

BOARD = "board-1"
POD = {"podId": "pod-1", "podName": "Pod One", "slug": "pod-one"}
FAKE_API_KEY = "da2-fake-not-a-real-key"


def make_jwt(claims):
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")  # noqa: E731
    return "%s.%s.fakesig" % (enc({"alg": "none"}), enc(claims))


POD_TOKEN = make_jwt({"sub": "sub-pod-user-1", "exp": int(time.time()) + 3600})
MAIN_TOKEN = make_jwt({"sub": "sub-main-user-1", "exp": int(time.time()) + 3600})

ALL_PAGE_ITEMS = {"items": [], "nextToken": None, "totalCount": 0}


def envelope(data=None, success=True, message="ok"):
    return {"success": success, "message": message, "data": data}


class FakeResponse:
    def __init__(self, body=b"", headers=None):
        self._body = body
        self.headers = headers or {}

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Transport:
    """Fake opener: routes AppSync POSTs by root field to `responders`; records every call."""

    ROOT_RE = re.compile(r"\n\s+((?:actionlists|actiongoals|filemanager|pods)_\w+)[\s({]")

    def __init__(self, responders=None):
        self.responders = responders or {}
        self.calls = []   # dicts: root, op, variables, headers
        self.other = []   # non-GraphQL requests (S3)

    def __call__(self, req, timeout=30):
        if "graphql" not in req.full_url:
            self.other.append((req.get_method(), req.full_url, req.data))
            return FakeResponse(b"", {"x-amz-bucket-region": "us-east-1"})
        payload = json.loads(req.data.decode())
        query = payload["query"]
        m = self.ROOT_RE.search(query)
        root = m.group(1) if m else None
        op = re.search(r"(?:query|mutation)\s+(\w+)", query).group(1)
        self.calls.append({"root": root, "op": op, "variables": payload.get("variables") or {},
                           "headers": {k.lower(): v for k, v in req.header_items()}, "query": query})
        resp = self.responders.get(root)
        data = resp(payload.get("variables") or {}) if callable(resp) else resp
        return FakeResponse(json.dumps({"data": {root: data}}).encode())

    def mutations(self, prefix=""):
        return [c for c in self.calls if c["query"].lstrip().startswith("mutation") and c["root"].startswith(prefix)]

    def deletes(self):
        return [c for c in self.calls if "_delete" in (c["root"] or "")]


AL = {"id": "al-1", "boardId": BOARD, "action": "List one", "actionListStatus": "New", "_version": 7}
ACT = {"id": "ac-1", "actionlistID": "al-1", "ActionItem": "Item one", "ActionStatus": "New", "_version": 3}
GOAL = {"id": "g-1", "boardId": BOARD, "title": "Goal one", "status": "PENDING", "priority": "LOW"}
FILE = {"id": "f-1", "boardId": BOARD, "folderId": "fo-1", "fileName": "report.txt", "fileSize": 5,
        "s3Object": {"bucket": "bucket-x", "key": "k/report.txt", "region": "us-east-1"}}


def default_responders():
    return {
        "actionlists_getAllActionLists": lambda v: envelope({"items": [AL], "nextToken": None, "totalCount": 1}),
        "actionlists_createActionList": lambda v: envelope(dict(AL, **{"action": v["input"]["action"]})),
        "actionlists_updateActionList": lambda v: envelope(dict(AL, **v["input"])),
        "actionlists_deleteActionList": lambda v: envelope({"id": v["input"]["id"], "boardId": BOARD,
                                                            "action": "List one", "_version": 8, "_deleted": True}),
        "actionlists_getAllActions": lambda v: envelope({"items": [ACT], "nextToken": None, "totalCount": 1}),
        "actionlists_getAction": lambda v: envelope(ACT),
        "actionlists_createAction": lambda v: envelope(dict(ACT, **v["input"])),
        "actionlists_updateAction": lambda v: envelope(dict(ACT, **v["input"])),
        "actionlists_deleteAction": lambda v: envelope({"id": v["input"]["id"], "actionlistID": "al-1",
                                                        "ActionItem": "Item one", "_version": 4, "_deleted": True}),
        "actiongoals_queryActionGoalsByBoardIdIndex": lambda v: envelope({"items": [GOAL, None], "nextToken": None}),
        "actiongoals_getActionGoal": lambda v: envelope(GOAL),
        "actiongoals_createActionGoal": lambda v: envelope(dict(GOAL, **v["input"])),
        "actiongoals_updateActionGoal": lambda v: envelope(dict(GOAL, **v["input"])),
        "actiongoals_deleteActionGoal": lambda v: envelope({"id": v["input"]["id"], "boardId": BOARD, "title": "Goal one"}),
        "filemanager_foldersByBoardIdIndex": lambda v: envelope(
            {"items": [{"id": "fo-1", "boardId": BOARD, "folderName": "Docs", "parentFolderId": None}]}),
        "filemanager_createFolder": lambda v: envelope(dict(v["input"], id="fo-2")),
        "filemanager_filesByBoardAndFolder": lambda v: envelope({"items": [FILE]}),
        "filemanager_getFile": lambda v: envelope(FILE),
        "filemanager_createFile": lambda v: envelope(dict(v["input"], id="f-2")),
        "filemanager_deleteFile": lambda v: envelope({"id": v["input"]["id"], "boardId": BOARD,
                                                      "folderId": "fo-1", "fileName": "report.txt"}),
        "pods_getMyPods": lambda v: envelope([{"podId": "pod-1", "bucketName": "bucket-x"}]),
    }


class PodCliCase(unittest.TestCase):
    def setUp(self):
        self._saved_edge = os.environ.pop("ACTIONBOARD_EDGE_PROXY_URL", None)
        self.tmp = tempfile.mkdtemp(prefix="ab-pod-test-")
        self.cred = os.path.join(self.tmp, "credentials.json")
        self.cfg = os.path.join(self.tmp, "config.json")
        with open(self.cred, "w") as fh:
            json.dump({"appsync_endpoint": "https://example.test/graphql", "appsync_api_key": FAKE_API_KEY}, fh)
        with open(self.cfg, "w") as fh:
            json.dump({"board_id": BOARD}, fh)
        self.transport = Transport(default_responders())
        patcher = mock.patch("actionboard_cli.commands._resolve_pod_token_and_profile",
                             return_value=(POD, POD_TOKEN, None))
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        if self._saved_edge is not None:
            os.environ["ACTIONBOARD_EDGE_PROXY_URL"] = self._saved_edge

    def run_cli(self, *argv, **kw):
        """Return (rc, stdout, stderr). SystemExit codes become rc."""
        base = ["--credentials-file", self.cred, "--config", self.cfg]
        out, err = io.StringIO(), io.StringIO()
        rc = 0
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                rc = submit_mission.main(base + list(argv), opener=kw.get("opener", self.transport))
            except SystemExit as exc:
                rc = exc.code
        return rc, out.getvalue(), err.getvalue()

    def last(self, root):
        return [c for c in self.transport.calls if c["root"] == root][-1]

    def ok(self, *argv):
        rc, out, err = self.run_cli(*argv, "--no-input", "--json")
        self.assertEqual(rc, 0, err)
        return json.loads(out)


class OperationTests(PodCliCase):
    def test_each_subcommand_sends_expected_operation_and_variables(self):
        cases = [
            (["actionlist", "list", "--status", "Done"], "Actionlists_getAllActionLists",
             lambda v: (v["input"]["boardId"] == BOARD and v["input"]["filter"] == {"actionListStatus": "Done"})),
            (["actionlist", "show", "al-1"], "Actionlists_getAllActionLists", lambda v: v["input"]["boardId"] == BOARD),
            (["actionlist", "create", "--title", "T", "--status", "New"], "Actionlists_createActionList",
             lambda v: v["input"] == {"action": "T", "actionListStatus": "New", "boardId": BOARD}),
            (["actionlist", "status", "al-1", "Done"], "Actionlists_updateActionList",
             lambda v: v["input"]["actionListStatus"] == "Done" and v["input"]["id"] == "al-1"),
            (["action", "list", "--list", "al-1", "--status", "New", "Done"], "Actionlists_getAllActions",
             lambda v: v["input"]["actionlistID"] == "al-1" and v["input"]["filter"] == {"actionStatus": ["New", "Done"]}),
            (["action", "get", "ac-1"], "Actionlists_getAction", lambda v: v == {"id": "ac-1"}),
            (["action", "create", "--list", "al-1", "--item", "I", "--status", "New"], "Actionlists_createAction",
             lambda v: v["input"]["actionlistID"] == "al-1" and v["input"]["ActionItem"] == "I"
             and v["input"]["ActionStatus"] == "New" and v["input"]["boardId"] == BOARD),
            (["action", "status", "ac-1", "In_Progress"], "Actionlists_updateAction",
             lambda v: v["input"]["ActionStatus"] == "In_Progress" and v["input"]["actionlistID"] == "al-1"),
            (["goal", "list"], "Actiongoals_queryActionGoalsByBoardIdIndex", lambda v: v["boardId"] == BOARD),
            (["goal", "get", "g-1"], "Actiongoals_getActionGoal", lambda v: v == {"id": "g-1", "boardId": BOARD}),
            (["goal", "create", "--title", "G", "--priority", "HIGH", "--status", "PENDING"],
             "Actiongoals_createActionGoal",
             lambda v: v["input"]["priority"] == "HIGH" and v["input"]["status"] == "PENDING"
             and v["input"]["title"] == "G" and v["input"]["boardId"] == BOARD),
            (["goal", "status", "g-1", "COMPLETED"], "Actiongoals_updateActionGoal",
             lambda v: v["input"] == {"status": "COMPLETED", "id": "g-1", "boardId": BOARD}),
            (["files", "folders"], "Filemanager_foldersByBoardIdIndex", lambda v: v["boardId"] == BOARD),
            (["files", "mkdir", "New Dir", "--parent", "fo-1"], "Filemanager_createFolder",
             lambda v: v["input"]["folderName"] == "New Dir" and v["input"]["parentFolderId"] == "fo-1"
             and v["input"]["boardId"] == BOARD),
            (["files", "list", "--folder", "fo-1"], "Filemanager_filesByBoardAndFolder",
             lambda v: v["boardId"] == BOARD and v["folderId"] == "fo-1"),
        ]
        for argv, op, check in cases:
            with self.subTest(argv=" ".join(argv)):
                self.transport.calls[:] = []
                rc, out, err = self.run_cli(*argv, "--no-input", "--json")
                self.assertEqual(rc, 0, err)
                self.assertIn(op, [c["op"] for c in self.transport.calls])
                call = [c for c in self.transport.calls if c["op"] == op][-1]
                self.assertTrue(check(call["variables"]), call["variables"])

    def test_delete_operations_with_yes(self):
        cases = [
            (["actionlist", "delete", "al-1"], "Actionlists_deleteActionList"),
            (["action", "delete", "ac-1"], "Actionlists_deleteAction"),
            (["goal", "delete", "g-1"], "Actiongoals_deleteActionGoal"),
            (["files", "delete", "f-1"], "Filemanager_deleteFile"),
        ]
        for argv, op in cases:
            with self.subTest(op=op):
                self.transport.calls[:] = []
                rc, _out, err = self.run_cli(*argv, "--no-input", "--json", "--yes")
                self.assertEqual(rc, 0, err)
                self.assertEqual([c["op"] for c in self.transport.deletes()], [op])

    def test_actionlist_update_sends_current_version(self):
        self.ok("actionlist", "update", "al-1", "--title", "Renamed")
        self.assertEqual(self.last("actionlists_updateActionList")["variables"]["input"]["_version"], 7)
        self.ok("actionlist", "status", "al-1", "Done")
        self.assertEqual(self.last("actionlists_updateActionList")["variables"]["input"]["_version"], 7)

    def test_action_update_sends_current_version_and_list_id(self):
        self.ok("action", "update", "ac-1", "--item", "Renamed")
        inp = self.last("actionlists_updateAction")["variables"]["input"]
        self.assertEqual(inp["_version"], 3)
        self.assertEqual(inp["actionlistID"], "al-1")

    def test_delete_actionlist_sends_version(self):
        rc, _o, err = self.run_cli("actionlist", "delete", "al-1", "--no-input", "--yes")
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.last("actionlists_deleteActionList")["variables"]["input"],
                         {"id": "al-1", "boardId": BOARD, "_version": 7})

    def test_update_of_missing_actionlist_is_refused_without_mutation(self):
        self.transport.responders["actionlists_getAllActionLists"] = lambda v: envelope(ALL_PAGE_ITEMS)
        rc, _out, err = self.run_cli("actionlist", "status", "nope", "Done", "--no-input")
        self.assertNotEqual(rc, 0)
        self.assertIn("not found", err)
        self.assertEqual(self.transport.mutations("actionlists_update"), [])

    def test_goal_user_id_is_pod_token_sub_not_creds_user(self):
        self.ok("goal", "create", "--title", "G", "--priority", "LOW")
        self.assertEqual(self.last("actiongoals_createActionGoal")["variables"]["input"]["userId"], "sub-pod-user-1")
        self.ok("goal", "create", "--title", "G", "--priority", "LOW", "--user-id", "someone")
        self.assertEqual(self.last("actiongoals_createActionGoal")["variables"]["input"]["userId"], "someone")

    def test_goal_list_uses_no_after_on_first_page_and_filters_null_items(self):
        data = self.ok("goal", "list")
        self.assertNotIn("after", self.last("actiongoals_queryActionGoalsByBoardIdIndex")["variables"])
        self.assertEqual([g["id"] for g in data["items"]], ["g-1"])

    def test_pod_token_is_the_bearer_and_board_override(self):
        self.ok("goal", "get", "g-1", "--board", "other-board")
        call = self.last("actiongoals_getActionGoal")
        self.assertEqual(call["variables"]["boardId"], "other-board")
        self.assertEqual(call["headers"]["authorization"], "Bearer " + POD_TOKEN)

    def test_missing_board_fails_cleanly(self):
        with open(self.cfg, "w") as fh:
            json.dump({}, fh)
        rc, _o, err = self.run_cli("goal", "list", "--no-input")
        self.assertNotEqual(rc, 0)
        self.assertIn("no board", err)

    def test_queries_use_variables_not_string_built_documents(self):
        evil = 'x" } mutation { evil }'
        self.ok("actionlist", "create", "--title", evil)
        call = self.last("actionlists_createActionList")
        self.assertNotIn("evil", call["query"])
        self.assertEqual(call["variables"]["input"]["action"], evil)


class ErrorHandlingTests(PodCliCase):
    def test_success_false_exits_nonzero_with_server_message(self):
        self.transport.responders["actionlists_createActionList"] = lambda v: envelope(
            None, success=False, message="Board is read-only")
        rc, out, err = self.run_cli("actionlist", "create", "--title", "T", "--no-input", "--json")
        self.assertNotEqual(rc, 0)
        self.assertIn("Board is read-only", err)
        self.assertEqual(out, "")

    def test_success_false_on_every_group(self):
        for argv, root in [(["goal", "get", "g-1"], "actiongoals_getActionGoal"),
                           (["action", "get", "ac-1"], "actionlists_getAction"),
                           (["files", "folders"], "filemanager_foldersByBoardIdIndex")]:
            with self.subTest(root=root):
                self.transport.responders[root] = lambda v: envelope(None, success=False, message="denied-xyz")
                rc, _o, err = self.run_cli(*argv, "--no-input")
                self.assertNotEqual(rc, 0)
                self.assertIn("denied-xyz", err)

    def test_graphql_errors_array_reports_message(self):
        def opener(req, timeout=30):
            return FakeResponse(json.dumps({"errors": [{"message": "Not authorized"}]}).encode())
        rc, _o, err = self.run_cli("goal", "list", "--no-input", opener=opener)
        self.assertNotEqual(rc, 0)
        self.assertIn("Not authorized", err)

    def test_enum_rejection_exits_2_without_calls(self):
        bad = [
            ["actionlist", "status", "al-1", "Bogus"],
            ["actionlist", "create", "--title", "T", "--status", "bogus"],
            ["actionlist", "list", "--status", "DONE"],
            ["action", "status", "ac-1", "Finished"],
            ["action", "list", "--list", "al-1", "--status", "Nope"],
            ["goal", "status", "g-1", "Done"],
            ["goal", "create", "--title", "T", "--priority", "URGENT"],
            ["goal", "create", "--title", "T", "--priority", "LOW", "--status", "New"],
        ]
        for argv in bad:
            with self.subTest(argv=argv):
                rc, _o, _e = self.run_cli(*argv, "--no-input")
                self.assertEqual(rc, 2)
        self.assertEqual(self.transport.calls, [])

    def test_service_layer_rejects_bad_enums_and_unknown_fields(self):
        s = {"endpoint": "https://x.test/graphql", "api_key": "k"}
        with self.assertRaises(ValueError):
            pod_services.create_goal(s, POD_TOKEN, BOARD, "t", "NOPE", user_id="u", opener=self.transport)
        with self.assertRaises(ValueError):
            pod_services.update_goal(s, POD_TOKEN, BOARD, "g", {"bogus": 1}, opener=self.transport)
        with self.assertRaises(ValueError):
            pod_services.update_actionlist(s, POD_TOKEN, BOARD, "a", {}, version=1, opener=self.transport)
        self.assertEqual(self.transport.calls, [])

    def test_error_text_is_scrubbed_of_tokens_and_signed_urls(self):
        leak = "Bearer abc.def.ghi and " + POD_TOKEN + " at https://b.s3.amazonaws.com/k?X-Amz-Signature=SIGSECRET"
        self.transport.responders["actiongoals_getActionGoal"] = lambda v: envelope(None, success=False, message=leak)
        rc, _o, err = self.run_cli("goal", "get", "g-1", "--no-input")
        self.assertNotEqual(rc, 0)
        for secret in (POD_TOKEN, "abc.def.ghi", "SIGSECRET", "X-Amz-Signature"):
            self.assertNotIn(secret, err)


class JsonOutputTests(PodCliCase):
    def test_json_shapes(self):
        page = self.ok("actionlist", "list")
        self.assertEqual(set(page), {"items", "nextToken", "totalCount"})
        self.assertEqual(page["items"][0]["id"], "al-1")
        self.assertEqual(self.ok("actionlist", "show", "al-1")["_version"], 7)
        self.assertEqual(self.ok("action", "get", "ac-1")["ActionStatus"], "New")
        self.assertEqual(set(self.ok("action", "list", "--list", "al-1")), {"items", "nextToken", "totalCount"})
        self.assertEqual(set(self.ok("goal", "list")), {"items", "nextToken"})
        folders = self.ok("files", "folders")
        self.assertIsInstance(folders, list)
        self.assertEqual(folders[0]["folderName"], "Docs")
        self.assertIsInstance(self.ok("files", "list", "--folder", "fo-1"), list)
        self.assertEqual(self.ok("goal", "status", "g-1", "IN_PROGRESS")["status"], "IN_PROGRESS")

    def test_json_output_is_only_json_on_stdout(self):
        rc, out, _err = self.run_cli("actionlist", "delete", "al-1", "--no-input", "--json", "--yes")
        self.assertEqual(rc, 0)
        # the "Delete <label>" preamble must not corrupt machine-readable output
        json.loads(out)


class DeleteConfirmationTests(PodCliCase):
    TARGETS = [
        ["actionlist", "delete", "al-1"],
        ["action", "delete", "ac-1"],
        ["goal", "delete", "g-1"],
        ["files", "delete", "f-1"],
    ]

    def test_no_input_without_yes_sends_zero_delete_mutations(self):
        for argv in self.TARGETS:
            with self.subTest(argv=argv):
                rc, _o, err = self.run_cli(*argv, "--no-input")
                self.assertEqual(rc, 2)
                self.assertIn("--yes", err)
                rc, _o, _e = self.run_cli(*argv, "--no-input", "--json")
                self.assertEqual(rc, 2)
        self.assertEqual(self.transport.deletes(), [])

    def test_non_tty_without_yes_is_refused_too(self):
        with mock.patch.object(sys.stdin, "isatty", return_value=False):
            rc, _o, _e = self.run_cli("goal", "delete", "g-1")
        self.assertEqual(rc, 2)
        self.assertEqual(self.transport.deletes(), [])

    def test_yes_sends_exactly_one_delete(self):
        for argv in self.TARGETS:
            with self.subTest(argv=argv):
                self.transport.calls[:] = []
                rc, _o, err = self.run_cli(*argv, "--no-input", "--yes")
                self.assertEqual(rc, 0, err)
                self.assertEqual(len(self.transport.deletes()), 1)

    def test_interactive_decline_sends_no_delete(self):
        with mock.patch.object(sys.stdin, "isatty", return_value=True), \
                mock.patch("builtins.input", return_value="n"):
            rc, _o, _e = self.run_cli("goal", "delete", "g-1")
        self.assertNotEqual(rc, 0)
        self.assertEqual(self.transport.deletes(), [])

    def test_interactive_accept_sends_one_delete(self):
        with mock.patch.object(sys.stdin, "isatty", return_value=True), \
                mock.patch("builtins.input", return_value="y"):
            rc, _o, err = self.run_cli("goal", "delete", "g-1")
        self.assertEqual(rc, 0, err)
        self.assertEqual(len(self.transport.deletes()), 1)


class DownloadSafetyTests(PodCliCase):
    def setUp(self):
        super().setUp()
        self.out = os.path.join(self.tmp, "out")
        os.makedirs(self.out)
        p = mock.patch("actionboard_cli.api.download_bytes_via_edge", return_value=b"hello")
        self.dl = p.start()
        self.addCleanup(p.stop)

    def serve_name(self, name):
        rec = dict(FILE, fileName=name)
        self.transport.responders["filemanager_getFile"] = lambda v: envelope(rec)

    def listing(self, directory=None):
        return sorted(os.listdir(directory or self.out))

    def test_normal_download_writes_inside_out_dir(self):
        rc, out, err = self.run_cli("files", "download", "f-1", "--out", self.out, "--no-input", "--json")
        self.assertEqual(rc, 0, err)
        res = json.loads(out)
        self.assertEqual(res["path"], os.path.join(os.path.realpath(self.out), "report.txt"))
        with open(res["path"], "rb") as fh:
            self.assertEqual(fh.read(), b"hello")

    def test_traversal_names_are_refused_and_nothing_escapes(self):
        parent_before = self.listing(self.tmp)
        for name in ("../../evil", "../evil", "..", ".", "", "/etc/evil", "a/../../evil",
                     "..\\..\\evil", "C:\\evil", "/", "///"):
            with self.subTest(name=name):
                self.serve_name(name)
                rc, _o, err = self.run_cli("files", "download", "f-1", "--out", self.out, "--no-input")
                self.assertNotEqual(rc, 0)
        self.assertEqual(self.listing(), [])
        self.assertEqual(self.listing(self.tmp), parent_before)
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(self.tmp), "evil")))

    def test_nested_name_is_reduced_to_basename_inside_out_dir(self):
        self.serve_name("sub/dir/file.txt")
        rc, out, err = self.run_cli("files", "download", "f-1", "--out", self.out, "--no-input", "--json")
        self.assertEqual(rc, 0, err)
        self.assertEqual(os.path.dirname(json.loads(out)["path"]), os.path.realpath(self.out))
        self.assertEqual(self.listing(), ["file.txt"])

    def test_existing_file_not_overwritten_without_flag(self):
        target = os.path.join(self.out, "report.txt")
        with open(target, "wb") as fh:
            fh.write(b"original")
        rc, _o, err = self.run_cli("files", "download", "f-1", "--out", self.out, "--no-input")
        self.assertNotEqual(rc, 0)
        self.assertIn("exists", err)
        with open(target, "rb") as fh:
            self.assertEqual(fh.read(), b"original")
        rc, _o, err = self.run_cli("files", "download", "f-1", "--out", self.out, "--no-input", "--overwrite")
        self.assertEqual(rc, 0, err)
        with open(target, "rb") as fh:
            self.assertEqual(fh.read(), b"hello")

    @unittest.skipIf(os.name == "nt", "symlinks need privileges on Windows")
    def test_symlink_target_is_refused_even_with_overwrite(self):
        victim = os.path.join(self.tmp, "victim.txt")
        with open(victim, "wb") as fh:
            fh.write(b"keep")
        os.symlink(victim, os.path.join(self.out, "report.txt"))
        for extra in ([], ["--overwrite"]):
            rc, _o, _e = self.run_cli("files", "download", "f-1", "--out", self.out, "--no-input", *extra)
            self.assertNotEqual(rc, 0)
        with open(victim, "rb") as fh:
            self.assertEqual(fh.read(), b"keep")

    def test_missing_out_dir_fails_and_creates_nothing(self):
        missing = os.path.join(self.tmp, "nope")
        rc, _o, _e = self.run_cli("files", "download", "f-1", "--out", missing, "--no-input")
        self.assertNotEqual(rc, 0)
        self.assertFalse(os.path.exists(missing))

    def test_file_without_stored_object_is_refused(self):
        self.transport.responders["filemanager_getFile"] = lambda v: envelope(dict(FILE, s3Object=None))
        rc, _o, err = self.run_cli("files", "download", "f-1", "--out", self.out, "--no-input")
        self.assertNotEqual(rc, 0)
        self.assertEqual(self.listing(), [])

    def test_safe_basename_unit(self):
        self.assertEqual(pod_services.safe_basename("a.txt"), "a.txt")
        self.assertEqual(pod_services.safe_basename("x/y.txt"), "y.txt")
        for bad in (None, "", ".", "..", "../x", "x/../y", "/abs", "C:x", "\x00", "///"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    pod_services.safe_basename(bad)


class OutputHygieneTests(PodCliCase):
    def test_control_characters_stripped_from_human_output(self):
        nasty = "evil\x1b[31mRED\x07\x00bell\r\nline2\x9bx\x7f"
        self.transport.responders["actionlists_getAllActionLists"] = lambda v: envelope(
            {"items": [dict(AL, action=nasty)], "nextToken": None})
        self.transport.responders["actiongoals_queryActionGoalsByBoardIdIndex"] = lambda v: envelope(
            {"items": [dict(GOAL, title=nasty)]})
        for argv in (["actionlist", "list"], ["actionlist", "show", "al-1"], ["goal", "list"]):
            with self.subTest(argv=argv):
                rc, out, _e = self.run_cli(*argv, "--no-input")
                self.assertEqual(rc, 0)
                for ch in ("\x1b", "\x07", "\x00", "\r", "\x9b", "\x7f"):
                    self.assertNotIn(ch, out)
                self.assertIn("evil", out)
                # one record = one line, so a "\n" in server text cannot forge extra rows
                if argv[1] == "list":
                    self.assertEqual(len(out.strip().splitlines()), 1)

    def test_bidi_and_line_separators_stripped_from_human_output(self):
        nasty = "a\u202eb\u200ec\u200fd\u202ae\u2066f\u2069g\u2028h\u2029i"
        self.transport.responders["actionlists_getAllActionLists"] = lambda v: envelope(
            {"items": [dict(AL, action=nasty)], "nextToken": None})
        rc, out, _e = self.run_cli("actionlist", "list", "--no-input")
        self.assertEqual(rc, 0)
        for ch in ("\u202e", "\u200e", "\u200f", "\u202a", "\u2066", "\u2069", "\u2028", "\u2029"):
            self.assertNotIn(ch, out)
        self.assertEqual(len(out.strip().splitlines()), 1)
        self.assertIn("a b c d e f g h i", out)

    def test_clean_helper(self):
        self.assertEqual(pod_commands._clean(None), "")
        self.assertEqual(pod_commands._clean("a\x1bb\nc"), "a b c")
        self.assertEqual(pod_commands._clean(5), "5")

    def test_no_secrets_in_any_output(self):
        secrets = (POD_TOKEN, MAIN_TOKEN, FAKE_API_KEY, "Authorization", "Bearer ", "X-Amz-Signature", "refresh")
        argvs = [["actionlist", "list"], ["actionlist", "create", "--title", "T"],
                 ["action", "status", "ac-1", "Done"], ["goal", "create", "--title", "G", "--priority", "LOW"],
                 ["files", "folders"], ["files", "list", "--folder", "fo-1"],
                 ["goal", "delete", "g-1", "--yes"]]
        for argv in argvs:
            for extra in ([], ["--json"]):
                with self.subTest(argv=argv, extra=extra):
                    _rc, out, err = self.run_cli(*argv, "--no-input", *extra)
                    for s in secrets:
                        self.assertNotIn(s, out)
                        self.assertNotIn(s, err)
        _rc, _o, err = self.run_cli("goal", "get", "g-1", "--board", "b", "--no-input",
                                    opener=lambda req, timeout=30: (_ for _ in ()).throw(OSError("boom")))
        self.assertNotIn(POD_TOKEN, err)

    def test_scrub_unit(self):
        text = "Bearer tok123 eyJhbGciOi.eyJzdWIiOiIx.sig https://h.s3.amazonaws.com/k?X-Amz-Signature=abc&X=1 end"
        out = pod_services._scrub(text)
        self.assertNotIn("tok123", out)
        self.assertNotIn("eyJzdWIi", out)
        self.assertNotIn("X-Amz-Signature", out)
        self.assertIn("https://h.s3.amazonaws.com/k?[redacted]", out)


class UploadBase(PodCliCase):
    def setUp(self):
        super().setUp()
        self.src = os.path.join(self.tmp, "up.txt")
        with open(self.src, "wb") as fh:
            fh.write(b"payload-bytes")
        self.presign_calls = []

        def fake_presign(settings, bucket, key, method, opener=None, expires_in=900, region=None):
            self.presign_calls.append((bucket, key, method, region))
            return "https://%s.s3.%s.amazonaws.com/%s?X-Amz-Signature=SIGSECRET" % (bucket, region, key), region

        for target, val in (("actionboard_cli.api.edge_presign", fake_presign),
                            ("actionboard_cli.auth.ensure_main_token", lambda *a, **k: MAIN_TOKEN)):
            p = mock.patch(target, side_effect=val)
            p.start()
            self.addCleanup(p.stop)

class UploadTests(UploadBase):
    def test_upload_flow_presign_put_then_create_file(self):
        rc, out, err = self.run_cli("files", "upload", self.src, "--folder", "fo-1", "--tags", "a, b",
                                    "--note", "n", "--no-input", "--json")
        self.assertEqual(rc, 0, err)
        puts = [o for o in self.transport.other if o[0] == "PUT"]
        self.assertEqual(len(puts), 1)
        self.assertEqual(puts[0][2], b"payload-bytes")
        self.assertEqual(self.presign_calls[0][0], "bucket-x")
        self.assertEqual(self.presign_calls[0][2], "PUT")
        inp = self.last("filemanager_createFile")["variables"]["input"]
        self.assertEqual((inp["boardId"], inp["folderId"], inp["fileName"], inp["fileSize"]),
                         (BOARD, "fo-1", "up.txt", 13))
        self.assertEqual(inp["tags"], ["a", "b"])
        self.assertEqual(inp["s3Object"]["bucket"], "bucket-x")
        self.assertTrue(inp["s3Object"]["key"].endswith("-up.txt"))
        self.assertNotIn("SIGSECRET", out + err)
        self.assertNotIn("X-Amz-Signature", out + err)
        self.assertEqual(json.loads(out)["id"], "f-2")

    def test_s3_head_sends_no_credentials(self):
        self.run_cli("files", "upload", self.src, "--folder", "fo-1", "--no-input")
        heads = [o for o in self.transport.other if o[0] == "HEAD"]
        self.assertTrue(heads)
        self.assertEqual(heads[0][1], "https://bucket-x.s3.amazonaws.com/")
        self.assertIsNone(heads[0][2])

    def test_upload_of_non_file_fails_without_network(self):
        rc, _o, err = self.run_cli("files", "upload", self.tmp, "--folder", "fo-1", "--no-input")
        self.assertNotEqual(rc, 0)
        self.assertEqual(self.transport.other, [])
        self.assertEqual(self.transport.mutations(), [])

    def test_failed_put_does_not_register_file_and_hides_signature(self):
        import urllib.error

        def opener(req, timeout=30):
            if req.get_method() == "PUT":
                raise urllib.error.URLError("conn reset https://b.s3.amazonaws.com/k?X-Amz-Signature=SIGSECRET")
            return self.transport(req, timeout)
        rc, out, err = self.run_cli("files", "upload", self.src, "--folder", "fo-1", "--no-input", opener=opener)
        self.assertNotEqual(rc, 0)
        self.assertNotIn("SIGSECRET", out + err)
        self.assertEqual(self.transport.mutations("filemanager_createFile"), [])


class BucketValidationTests(UploadBase):
    BAD = ("evil.com/#", "a..b", "1.2.3.4", "UPPER", "a b", "x/../y")

    def heads(self):
        return [o for o in self.transport.other if o[0] == "HEAD"]

    def test_invalid_bucket_sends_no_head_and_upload_uses_fallback_region(self):
        for bad in self.BAD:
            with self.subTest(bucket=bad):
                self.transport.other[:] = []
                self.presign_calls[:] = []
                self.transport.responders["pods_getMyPods"] = lambda v, b=bad: envelope(
                    [{"podId": "pod-1", "bucketName": b}])
                rc, _o, _e = self.run_cli("files", "upload", self.src, "--folder", "fo-1", "--no-input")
                self.assertEqual(self.heads(), [])
                if self.presign_calls:  # an upload may proceed with the configured fallback region only
                    self.assertTrue(self.presign_calls[0][3])
                    self.assertNotIn("evil.com", self.presign_calls[0][3])

    def test_bucket_region_helper_rejects_without_request_and_validates_header(self):
        import urllib.error
        seen = []

        def opener(req, timeout=30):
            seen.append(req.full_url)
            raise urllib.error.HTTPError(req.full_url, 301, "moved", {"x-amz-bucket-region": HDR[0]}, None)
        HDR = ["us-west-2"]
        for bad in self.BAD:
            self.assertIsNone(pod_services._bucket_region(bad, opener))
        self.assertIsNone(pod_services._bucket_region(None, opener))
        self.assertEqual(seen, [])
        self.assertEqual(pod_services._bucket_region("good-bucket", opener), "us-west-2")
        for bogus in ("evil.com/x", "us west", "<script>", "UPPER-1", "x" * 5):
            HDR[0] = bogus
            self.assertIsNone(pod_services._bucket_region("good-bucket", opener), bogus)

    def test_download_with_invalid_bucket_sends_no_head_and_fails_cleanly(self):
        out = os.path.join(self.tmp, "o")
        os.makedirs(out)
        rec = dict(FILE, s3Object={"bucket": "evil.com/#", "key": "k", "region": "us-east-1"})
        self.transport.responders["filemanager_getFile"] = lambda v: envelope(rec)
        with mock.patch("actionboard_cli.api.download_bytes_via_edge", side_effect=RuntimeError("S3 GET HTTP 403")) as dl:
            rc, _o, _e = self.run_cli("files", "download", "f-1", "--out", out, "--no-input")
        self.assertNotEqual(rc, 0)
        self.assertEqual(self.heads(), [])
        self.assertEqual(dl.call_count, 1)
        self.assertEqual(os.listdir(out), [])


class RegistrationAndSchemaTests(unittest.TestCase):
    def help_text(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                submit_mission.main(list(argv) + ["--help"])
        self.assertEqual(ctx.exception.code, 0)
        return out.getvalue()

    def test_help_lists_every_verb(self):
        expect = {
            "actionlist": ("list", "show", "create", "update", "status", "delete"),
            "action": ("list", "get", "create", "update", "status", "delete"),
            "goal": ("list", "get", "create", "update", "status", "delete"),
            "files": ("folders", "mkdir", "list", "upload", "download", "delete"),
        }
        for group, verbs in expect.items():
            text = self.help_text(group)
            for verb in verbs:
                with self.subTest(group=group, verb=verb):
                    self.assertRegex(text, r"(?m)^\s+%s\s" % verb)

    def test_delete_help_mentions_yes(self):
        for group in ("actionlist", "action", "goal", "files"):
            self.assertIn("--yes", self.help_text(group, "delete"))

    def test_query_my_pods_does_not_select_region(self):
        self.assertNotRegex(operations.QUERY_MY_PODS, r"\bregion\b")

    def test_new_documents_are_static_and_parameterised(self):
        names = [n for n in dir(operations) if n.startswith(("QUERY_", "MUTATION_"))]
        self.assertTrue(names)
        for n in names:
            self.assertNotIn("%s", getattr(operations, n), n)
            self.assertNotIn("{0}", getattr(operations, n), n)

    def test_modules_parse_with_python39_grammar(self):
        for name in ("pod_services.py", "pod_commands.py"):
            path = os.path.join(SCRIPTS_DIR, "actionboard_cli", name)
            with open(path, encoding="utf-8") as fh:
                ast.parse(fh.read(), filename=path, feature_version=(3, 9))

    def test_enum_tuples_match_schema(self):
        self.assertEqual(pod_services.GOAL_STATUSES, ("PENDING", "IN_PROGRESS", "COMPLETED"))
        self.assertEqual(pod_services.GOAL_PRIORITIES, ("LOW", "MEDIUM", "HIGH"))
        for status in ("New", "In_Progress", "Done"):
            self.assertIn(status, pod_services.ACTIONLIST_STATUSES)


if __name__ == "__main__":
    unittest.main()
