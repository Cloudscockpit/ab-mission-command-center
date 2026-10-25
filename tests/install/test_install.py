"""Install/uninstall round trip into a throwaway project for every file-based target."""

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import install  # noqa: E402

USER_HOOKS = {"hooks": {"PreToolUse": [{"matcher": "x", "hooks": [{"type": "command", "command": "echo mine"}]}]}}


def run(*args):
    with contextlib.redirect_stdout(io.StringIO()) as out:
        code = install.main(list(args))
    return code, out.getvalue()


def snapshot(root):
    out = {}
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d != ".git"]
        for f in fn:
            with open(os.path.join(dp, f), "rb") as fh:
                out[os.path.relpath(os.path.join(dp, f), root)] = fh.read()
        if not fn and not dn and dp != root:
            out[os.path.relpath(dp, root) + os.sep] = b""
    return out


class RoundTrip(unittest.TestCase):
    def setUp(self):
        self.project = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.project, ".codex"))
        with open(os.path.join(self.project, "AGENTS.md"), "w", encoding="utf-8") as fh:
            fh.write("# existing\n")
        with open(os.path.join(self.project, ".codex", "hooks.json"), "w", encoding="utf-8") as fh:
            json.dump(USER_HOOKS, fh)
        self.before = snapshot(self.project)

    def tearDown(self):
        shutil.rmtree(self.project, ignore_errors=True)

    def hooks(self):
        with open(os.path.join(self.project, ".codex", "hooks.json"), encoding="utf-8") as fh:
            return json.load(fh)["hooks"]

    def test_install_twice_then_uninstall_restores_project(self):
        for _ in range(2):  # reinstall must be idempotent
            for t in ("opencode", "codex", "antigravity"):
                self.assertEqual(run("--target", t, "--project", self.project)[0], 0, t)
        pre = self.hooks()["PreToolUse"]
        self.assertEqual(len(pre), 2)
        self.assertNotIn("__PYTHON__", json.dumps(pre))
        with open(os.path.join(self.project, "AGENTS.md"), encoding="utf-8") as fh:
            self.assertEqual(fh.read().count("actionboard:begin"), 1)
        for rel in (".opencode/agents/black-agent.md", ".opencode/plugins/actionboard-guard.ts",
                    ".agents/skills/start-mission/SKILL.md", ".codex/agents/red-agent.toml",
                    ".codex/rules/actionboard.rules",
                    ".agents/plugins/actionboard-v5-agentformation/plugin.json"):
            self.assertTrue(os.path.exists(os.path.join(self.project, rel)), rel)
        with open(os.path.join(self.project, ".agents/plugins/actionboard-v5-agentformation/hooks.json"),
                  encoding="utf-8") as fh:
            self.assertNotIn("__PYTHON__", fh.read())

        for t in ("opencode", "codex", "antigravity"):
            self.assertEqual(run("--target", t, "--project", self.project, "--uninstall")[0], 0, t)
        after = snapshot(self.project)
        self.assertEqual(sorted(after), sorted(self.before))
        self.assertEqual(self.hooks(), USER_HOOKS["hooks"])
        self.assertEqual(after["AGENTS.md"].replace(b"\r\n", b"\n"), b"# existing\n")

    def test_refuses_to_overwrite_foreign_files(self):
        path = os.path.join(self.project, ".opencode", "agents", "red-agent.md")
        os.makedirs(os.path.dirname(path))
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("mine")
        code, out = run("--target", "opencode", "--project", self.project)
        self.assertEqual(code, 1)
        self.assertIn("Refusing to overwrite", out)
        with open(path, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "mine")

    def test_uninstall_keeps_modified_files(self):
        run("--target", "opencode", "--project", self.project)
        path = os.path.join(self.project, ".opencode", "agents", "red-agent.md")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("\nlocal tweak\n")
        code, out = run("--target", "opencode", "--project", self.project, "--uninstall")
        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists(path))
        self.assertIn("kept (modified since install)", out)

    def test_context7_added_and_removed(self):
        self.assertEqual(run("--target", "opencode", "--project", self.project)[0], 0)
        self.assertEqual(run("--target", "codex", "--project", self.project)[0], 0)
        with open(os.path.join(self.project, "opencode.json"), encoding="utf-8") as fh:
            server = json.load(fh)["mcp"]["context7"]
        self.assertEqual(server, {"type": "remote", "url": "https://mcp.context7.com/mcp", "enabled": True})
        with open(os.path.join(self.project, ".codex", "config.toml"), encoding="utf-8") as fh:
            self.assertIn('[mcp_servers.context7]\nurl = "https://mcp.context7.com/mcp"', fh.read())
        for t in ("opencode", "codex"):
            run("--target", t, "--project", self.project, "--uninstall")
        self.assertFalse(os.path.exists(os.path.join(self.project, "opencode.json")))
        self.assertFalse(os.path.exists(os.path.join(self.project, ".codex", "config.toml")))

    def test_user_context7_is_never_touched(self):
        mine_json = {"mcp": {"context7": {"type": "local", "command": ["my-context7"]}}, "theme": "x"}
        mine_toml = '# mine\n[mcp_servers.context7]\ncommand = "my-context7"\n'
        with open(os.path.join(self.project, "opencode.json"), "w", encoding="utf-8") as fh:
            json.dump(mine_json, fh)
        with open(os.path.join(self.project, ".codex", "config.toml"), "w", encoding="utf-8") as fh:
            fh.write(mine_toml)
        for t in ("opencode", "codex"):
            self.assertEqual(run("--target", t, "--project", self.project)[0], 0)
            run("--target", t, "--project", self.project, "--uninstall")
        with open(os.path.join(self.project, "opencode.json"), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), mine_json)
        with open(os.path.join(self.project, ".codex", "config.toml"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), mine_toml)

    def test_codex_config_keeps_user_settings(self):
        path = os.path.join(self.project, ".codex", "config.toml")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write('model = "gpt-x"\n')
        run("--target", "codex", "--project", self.project)
        run("--target", "codex", "--project", self.project)  # idempotent
        with open(path, encoding="utf-8") as fh:
            self.assertEqual(fh.read().count("[mcp_servers.context7]"), 1)
        run("--target", "codex", "--project", self.project, "--uninstall")
        with open(path, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), 'model = "gpt-x"\n')

    def prefs(self):
        with open(os.path.join(self.project, ".actionboard", "preferences.json"), encoding="utf-8") as fh:
            return json.load(fh)

    def test_opt_in_flags_record_preferences(self):
        installed = []
        original = install.install_graphify
        install.install_graphify = lambda dry: installed.append(dry) or True
        try:
            run("--target", "opencode", "--project", self.project, "--with", "graphify,terse")
        finally:
            install.install_graphify = original
        self.assertEqual(installed, [False])
        self.assertEqual(self.prefs(), {"graphify": "enabled", "terse_output": "enabled"})
        run("--target", "opencode", "--project", self.project, "--without", "terse")
        self.assertEqual(self.prefs(), {"graphify": "enabled", "terse_output": "declined"})

    def test_no_flags_and_no_tty_leaves_choice_to_preflight(self):
        run("--target", "opencode", "--project", self.project, "--yes")
        self.assertFalse(os.path.exists(os.path.join(self.project, ".actionboard")))
        with self.assertRaises(SystemExit):
            install.main(["--target", "opencode", "--project", self.project, "--with", "nope"])

    def test_dry_run_writes_nothing(self):
        run("--target", "codex", "--project", self.project, "--dry-run")
        self.assertEqual(snapshot(self.project), self.before)


if __name__ == "__main__":
    unittest.main()
