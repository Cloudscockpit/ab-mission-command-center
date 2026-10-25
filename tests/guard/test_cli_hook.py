"""Native payload translation for the Claude, Codex, and Antigravity hook adapter."""

import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOK = os.path.join(ROOT, "adapters", "common", "hooks", "cli_hook.py")
# cli_hook imports core/ from its own directory, so run it from a built tree.
BUILT = {
    "claude": os.path.join(ROOT, "dist", "claude", "hooks", "cli_hook.py"),
    "codex": os.path.join(ROOT, "dist", "codex", ".codex", "actionboard", "hooks", "cli_hook.py"),
    "antigravity": os.path.join(ROOT, "dist", "antigravity", "actionboard", "hooks", "cli_hook.py"),
}


def payload(cli, command, tool=None):
    if cli == "antigravity":
        return {"toolCall": {"name": tool or "run_command", "args": {"CommandLine": command}},
                "conversationId": "c1", "workspacePaths": [tempfile.gettempdir()]}
    return {"session_id": "s1", "cwd": tempfile.gettempdir(), "hook_event_name": "PreToolUse",
            "tool_name": tool or "Bash", "tool_input": {"command": command}}


HOME = tempfile.mkdtemp()  # no agy settings.json unless a test writes one


def call(cli, event, data, home=HOME):
    stdin = data if isinstance(data, str) else json.dumps(data)
    env = dict(os.environ, HOME=home, USERPROFILE=home)
    proc = subprocess.run([sys.executable, BUILT[cli], "--cli", cli, "--event", event],
                          input=stdin, capture_output=True, text=True, env=env)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout) if proc.stdout.strip() else None


def decision(cli, out):
    if out is None:
        return "allow"
    if cli == "antigravity":
        # agy: "ask" defers to the user's own approval setting (no objection);
        # "force_ask" is the guard asking.
        return {"ask": "allow", "force_ask": "ask"}.get(out["decision"], out["decision"])
    return out["hookSpecificOutput"]["permissionDecision"]


class Pre(unittest.TestCase):
    def test_built_copies_match_adapter(self):
        with open(HOOK, "rb") as fh:
            src = fh.read()
        for cli, path in BUILT.items():
            with open(path, "rb") as fh:
                self.assertEqual(fh.read(), src, cli)

    def test_allow_deny_ask_per_cli(self):
        cases = {
            "ls": ("allow", "allow", "allow"),
            "openshell sandbox delete --all": ("deny", "deny", "deny"),
            "openshell workspace delete team": ("ask", "allow", "ask"),       # codex: .rules prompts
            'bash -c "openshell workspace delete team"': ("ask", "deny", "ask"),
            "openshell sandbox create --add-endpoint a.b:443:full": ("ask", "deny", "ask"),
            # Codex prefix rules match leading literal tokens only: reordered flags are denied.
            "openshell policy set --global -f p.yaml": ("ask", "allow", "ask"),
            "openshell policy --global set": ("ask", "deny", "ask"),
            "openshell workspace --yes delete acme": ("ask", "deny", "ask"),
        }
        for command, expected in cases.items():
            for cli, want in zip(("claude", "codex", "antigravity"), expected):
                got = decision(cli, call(cli, "pre", payload(cli, command)))
                self.assertEqual(got, want, "%s / %s" % (cli, command))

    def test_claude_powershell_tool_is_guarded(self):
        out = call("claude", "pre", payload("claude", "openshell sandbox delete --all", "PowerShell"))
        self.assertEqual(decision("claude", out), "deny")

    def test_other_tools_ignored(self):
        self.assertIsNone(call("claude", "pre", payload("claude", "openshell sandbox delete --all", "Read")))
        out = call("antigravity", "pre", payload("antigravity", "openshell sandbox delete --all", "view_file"))
        self.assertEqual(out, {"decision": "ask"})

    def test_antigravity_never_sends_allow(self):
        # agy's "allow" auto-approves and skips the user's own approval setting;
        # an object without a decision is a deny (both verified live on agy 1.4.7).
        for command in ("ls", "git push", "openshell sandbox list"):
            self.assertEqual(call("antigravity", "pre", payload("antigravity", command)),
                             {"decision": "ask"}, command)
        self.assertEqual(call("antigravity", "pre", "garbage"), {"decision": "ask"})
        out = call("antigravity", "pre", payload("antigravity", "openshell workspace delete team"))
        self.assertEqual(out["decision"], "force_ask")

    def test_antigravity_always_proceed_turns_asks_into_denies(self):
        home = tempfile.mkdtemp()
        os.makedirs(os.path.join(home, ".gemini", "antigravity-cli"))
        with open(os.path.join(home, ".gemini", "antigravity-cli", "settings.json"), "w") as fh:
            json.dump({"toolPermission": "always-proceed"}, fh)
        out = call("antigravity", "pre", payload("antigravity", "openshell workspace delete team"), home)
        self.assertEqual(out["decision"], "deny")
        self.assertIn("always-proceed", out["reason"])
        self.assertEqual(call("antigravity", "pre", payload("antigravity", "ls"), home), {"decision": "ask"})

    def test_garbage_payload_fails_closed(self):
        self.assertEqual(decision("claude", call("claude", "pre", "{openshell")), "ask")
        self.assertEqual(decision("codex", call("codex", "pre", "{openshell")), "deny")
        self.assertEqual(decision("antigravity", call("antigravity", "pre", "{openshell")), "ask")
        self.assertEqual(decision("claude", call("claude", "pre", "garbage")), "allow")

    def test_undecodable_bytes_fail_closed(self):
        raw = b'{"tool_name":"Bash","tool_input":{"command":"echo \x81\xff && openshell sandbox delete --all"}}'
        proc = subprocess.run([sys.executable, BUILT["claude"], "--cli", "claude", "--event", "pre"],
                              input=raw, capture_output=True)
        self.assertEqual(proc.returncode, 0)
        self.assertIn(json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"], ("ask", "deny"))

    def test_codex_exec_command_cmd_key(self):
        data = payload("codex", "", "exec_command")
        data["tool_input"] = {"cmd": "openshell sandbox delete --all"}
        self.assertEqual(decision("codex", call("codex", "pre", data)), "deny")

    def test_bad_arguments_still_answer(self):
        proc = subprocess.run([sys.executable, BUILT["claude"], "--cli", "nope", "--event", "pre"],
                              input='{"tool_input":{"command":"openshell x"}}', capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"], "ask")


class Post(unittest.TestCase):
    def test_audit_written_for_each_cli(self):
        for cli in BUILT:
            d = tempfile.mkdtemp()
            data = payload(cli, "openshell policy set -f p.yaml")
            if cli == "antigravity":
                data["workspacePaths"] = [d]
            else:
                data["cwd"] = d
            out = call(cli, "post", data)
            self.assertEqual(out, {} if cli == "antigravity" else None)
            with open(os.path.join(d, ".openshell-audit.log"), encoding="utf-8") as fh:
                self.assertIn("\tpolicy set\t", fh.read(), cli)


if __name__ == "__main__":
    unittest.main()
