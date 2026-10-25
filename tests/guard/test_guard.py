"""Unit tests for the CLI-agnostic hook core. Run: python -m pytest tests/guard
(or python -m unittest discover -s tests/guard)."""

import datetime
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CORE = os.path.join(ROOT, "src", "hooks", "core")
sys.path.insert(0, CORE)

import audit  # noqa: E402
import guard  # noqa: E402
import openshell  # noqa: E402


def decision(command):
    return guard.decide({"tool": "bash", "command": command})["decision"]


class GuardDecisions(unittest.TestCase):
    def test_unrelated_commands_pass(self):
        for cmd in ("ls -la", "git status", "echo 'unbalanced", ""):
            self.assertEqual(decision(cmd), "allow", cmd)

    def test_read_only_openshell_passes(self):
        self.assertEqual(decision("openshell sandbox list --output json"), "allow")
        self.assertEqual(decision("openshell sandbox delete my-box"), "allow")

    def test_cross_workspace_delete_denied(self):
        for cmd in ("openshell sandbox delete --all-workspaces",
                    "openshell sandbox delete --all",
                    'openshell sandbox delete --all-work"spaces"',     # quote bypass
                    "openshell   sandbox   delete   --all-workspaces",  # whitespace
                    "/usr/local/bin/openshell sandbox delete --all"):
            self.assertEqual(decision(cmd), "deny", cmd)

    def test_wrappers_and_chains(self):
        for cmd in ('bash -c "openshell sandbox delete --all"',
                    "sh -c 'echo hi && openshell sandbox delete --all'",
                    "FOO=1 BAR=2 openshell sandbox delete --all",
                    "env sudo openshell sandbox delete --all",
                    "ls; openshell sandbox delete --all",
                    "true || openshell sandbox delete --all",
                    "cat x | openshell sandbox delete --all",
                    "ls\nopenshell sandbox delete --all"):
            self.assertEqual(decision(cmd), "deny", cmd)

    def test_global_policy_asks(self):
        self.assertEqual(decision("openshell policy set --global -f p.yaml"), "ask")
        self.assertEqual(decision("openshell policy set -f p.yaml"), "allow")

    def test_workspace_delete_asks(self):
        self.assertEqual(decision("openshell workspace delete team-a"), "ask")

    def test_flag_equals_value(self):
        self.assertEqual(decision("openshell sandbox create --env=GITHUB_TOKEN=x"), "deny")
        self.assertEqual(decision("openshell sandbox update -e AWS_ACCESS_KEY_ID=x"), "deny")
        self.assertEqual(decision("openshell sandbox create --add-endpoint=api.x.com:443:full"), "ask")
        self.assertEqual(decision("openshell sandbox create --add-endpoint api.x.com:443:full"), "ask")

    def test_credential_segments(self):
        for var in ("GITHUB_TOKEN", "API_KEY", "CLIENT_SECRET", "db-password", "MY_PAT"):
            self.assertTrue(openshell.credential_like(var), var)
        for var in ("TOKENIZERS_PARALLELISM", "PASSWORDLESS_LOGIN", "LOG_LEVEL"):
            self.assertFalse(openshell.credential_like(var), var)
        self.assertEqual(decision("openshell sandbox create --env TOKENIZERS_PARALLELISM=0"), "allow")

    def test_indirect_invocations_fail_closed(self):
        for cmd in ("echo $(openshell sandbox delete --all-workspaces)",
                    "echo `openshell workspace delete a`",
                    "eval 'openshell sandbox delete --all'",
                    "echo sandbox | xargs openshell",
                    "(openshell sandbox delete --all)",
                    "ls && { openshell sandbox delete x; }"):
            self.assertIn(decision(cmd), ("ask", "deny"), cmd)
        self.assertEqual(decision("cat docs/openshell-notes.md"), "allow")

    def test_review_bypasses_are_closed(self):
        """Security review 2026-10-25: every one of these used to return allow (or ask
        instead of deny). Each must now be deny or ask."""
        not_allowed = [
            "openshell sandbox list & openshell sandbox delete --all-workspaces",
            "openshell status & openshell sandbox delete mybox --all",
            "openshell sandbox list |& openshell sandbox delete --all",
            'echo "openshell sandbox delete --all-workspaces" | sh',
            "printf 'openshell sandbox delete --all-workspaces' > x.sh && sh x.sh",
            "python -c \"import subprocess; subprocess.run(['openshell','sandbox','delete','--all'])\"",
            'iex "openshell sandbox delete --all-workspaces"',
            ".\\openshell.exe sandbox delete --all-workspaces",
            "C:\\tools\\openshell.exe sandbox delete --all-workspaces",
            "sudo -u root openshell sandbox delete --all-workspaces",
            "& openshell sandbox delete --all-workspaces",
            "OPENSHELL sandbox delete --all-workspaces",
            "op''enshell sandbox delete --all-workspaces",
            '"ope"nshell sandbox delete --all-workspaces',
            "op\\enshell sandbox delete --all-workspaces",
            "V=delete; openshell sandbox $V --all-workspaces",
            "openshell sandbox delete $'--all-workspaces'",
            "powershell -EncodedCommand bwBwAGUAbgBzAGgAZQBsAGwA",
            "pwsh -enc bwBwAGUAbgBzAGgAZQBsAGwA",
            'sh -c "sh -c \\"sh -c \'sh -c \\\\\\"openshell sandbox delete --all\\\\\\"\'\\""',
        ]
        for cmd in not_allowed:
            self.assertIn(decision(cmd), ("ask", "deny"), cmd)
        must_deny = [
            "env -i openshell sandbox delete --all-workspaces",
            "nice -n 10 openshell sandbox delete --all-workspaces",
            "timeout 60 openshell sandbox delete --all-workspaces",
            "command -p openshell sandbox delete --all-workspaces",
            'cmd /c "openshell sandbox delete --all-workspaces"',
            'bash -lc "openshell sandbox delete --all-workspaces"',
            "sh -ec 'openshell sandbox delete --all'",
            "openshell --workspace acme sandbox delete --all-workspaces",
            "openshell workspace delete a && openshell sandbox delete --all-workspaces",
            "openshell sandbox create --env MYTOKEN=abc123",
            "openshell sandbox create --env DBPASS=hunter2",
        ]
        for cmd in must_deny:
            self.assertEqual(decision(cmd), "deny", cmd)
        self.assertEqual(decision("openshell --profile prod policy set --global"), "ask")
        self.assertEqual(decision("openshell sandbox create --add-endpoint a.b:443:FULL"), "ask")
        self.assertEqual(guard.decide({"command": "openshell policy --global set"})["rule"], "global-policy")

    def test_no_false_positives_on_neighbours(self):
        for cmd in ("cat skills/openshell-admin/SKILL.md",
                    "ls policies/openshell-notes.md",
                    "openshell sandbox list --output json | jq .",
                    "openshell sandbox create --env TOKENIZERS_PARALLELISM=false --env LOG_LEVEL=debug"):
            self.assertEqual(decision(cmd), "allow", cmd)

    def test_unbalanced_quotes_fail_closed(self):
        self.assertEqual(decision("openshell sandbox delete 'oops"), "ask")

    def test_plain_flag(self):
        plain = guard.decide({"command": "openshell workspace delete team-a"})
        self.assertTrue(plain["plain"])
        wrapped = guard.decide({"command": 'bash -c "openshell workspace delete team-a"'})
        self.assertEqual(wrapped["decision"], "ask")
        self.assertFalse(wrapped["plain"])
        self.assertFalse(guard.decide({"command": "openshell workspace delete 'a'"})["plain"])


class GuardCli(unittest.TestCase):
    def run_guard(self, stdin):
        proc = subprocess.run([sys.executable, os.path.join(CORE, "guard.py")],
                              input=stdin, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0)
        return json.loads(proc.stdout)

    def test_cli_roundtrip(self):
        out = self.run_guard(json.dumps({"tool": "bash", "command": "openshell sandbox delete --all"}))
        self.assertEqual(out["decision"], "deny")
        self.assertIn("cross-workspace", out["reason"])

    def test_malformed_payload_mentioning_openshell_fails_closed(self):
        self.assertEqual(self.run_guard('{"command": "openshell sandbox')["decision"], "ask")

    def test_malformed_unrelated_payload_allows(self):
        self.assertEqual(self.run_guard("not json")["decision"], "allow")

    def test_non_string_command(self):
        self.assertEqual(self.run_guard('{"command": ["openshell"]}')["decision"], "ask")


class Audit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ.pop("OPENSHELL_AUDIT_LOG", None)

    def read_log(self):
        with open(os.path.join(self.tmp, ".openshell-audit.log"), encoding="utf-8") as fh:
            return fh.read().splitlines()

    def test_records_mutations_only(self):
        now = datetime.datetime(2026, 1, 2, 3, 4, 5, tzinfo=datetime.timezone.utc)
        payload = {"command": "openshell sandbox list && openshell  policy set -f p.yaml",
                   "session": "s1", "cwd": self.tmp}
        audit.record(payload, now=now)
        self.assertEqual(self.read_log(),
                         ["2026-01-02T03:04:05Z\ts1\tpolicy set\topenshell policy set -f p.yaml"])

    def test_wrapped_and_unparsed(self):
        audit.record({"command": 'bash -c "openshell workspace delete a"; openshell sandbox delete \'x',
                      "cwd": self.tmp})
        lines = self.read_log()
        self.assertEqual(len(lines), 2)
        self.assertIn("\tnosession\tworkspace delete\t", lines[0])
        self.assertIn("\tUNPARSED\t", lines[1])

    def test_env_override(self):
        target = os.path.join(self.tmp, "custom.log")
        os.environ["OPENSHELL_AUDIT_LOG"] = target
        try:
            audit.record({"command": "openshell provider add x", "cwd": "/nonexistent"})
        finally:
            os.environ.pop("OPENSHELL_AUDIT_LOG")
        self.assertTrue(os.path.exists(target))

    def test_cli_never_fails(self):
        for stdin in ("garbage openshell", "{}", json.dumps({"command": 5})):
            proc = subprocess.run([sys.executable, os.path.join(CORE, "audit.py")],
                                  input=stdin, capture_output=True, text=True, cwd=self.tmp)
            self.assertEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()
