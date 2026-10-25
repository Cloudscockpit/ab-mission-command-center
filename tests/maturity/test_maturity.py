"""Maturity recording and the Maturity & Progress Summary (maturity.py)."""

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src", "skills", "actionboard-devops-mission", "scripts"))

import gate_check  # noqa: E402
import maturity  # noqa: E402

ALL_PASS = "orchestrator=pass,data=pass,analysis=pass,action=pass,defense=pass"


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.reg = os.path.join(self.dir, ".actionboard", "registry.json")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def record(self, run_id, stages=ALL_PASS, action="deploy", mission="m", tier="T2", *extra):
        args = ["record", "--registry", self.reg, "--action", action, "--run-id", run_id,
                "--mission", mission, "--mode", "actionlist", "--stages", stages,
                "--name", action.title(), "--risk-tier", tier, "--end-condition", "it works"] + list(extra)
        with contextlib.redirect_stdout(io.StringIO()):
            return maturity.main(args)

    def summary(self, mission="m", level="L4", fmt="--json"):
        out = io.StringIO()
        args = ["summary", "--registry", self.reg, "--mission", mission, "--operator-level", level]
        with contextlib.redirect_stdout(out):
            maturity.main(args + ([fmt] if fmt else []))
        return json.loads(out.getvalue()) if fmt else out.getvalue()

    def action(self, name="deploy"):
        with open(self.reg, encoding="utf-8") as fh:
            return next(a for a in json.load(fh)["actions"] if a["id"] == name)


class Recording(Base):
    def test_registers_then_appends(self):
        self.record("r1")
        self.record("r2", mission="m2")
        a = self.action()
        self.assertEqual([r["run_id"] for r in a["runs"]], ["r1", "r2"])
        self.assertEqual(a["missions"], ["m", "m2"])
        self.assertEqual(a["runs"][0]["provenance"], "scored")

    def test_runs_are_append_only(self):
        self.record("r1")
        with self.assertRaises(SystemExit):
            self.record("r1")

    def test_unscored_stage_is_a_failure(self):
        self.record("r1", "orchestrator=pass,data=pass,analysis=pass,action=pass")
        self.assertFalse(self.action()["runs"][0]["stages"]["defense"])

    def test_retry_to_green_fails_the_action_stage(self):
        self.record("r1", ALL_PASS, "deploy", "m", "T2", "--retried")
        run = self.action()["runs"][0]
        self.assertFalse(run["stages"]["action"])
        self.assertFalse(run["first_attempt"])

    def test_unregistered_action_needs_metadata(self):
        with self.assertRaises(SystemExit):
            maturity.main(["record", "--registry", self.reg, "--action", "x", "--run-id", "r",
                           "--mode", "guided", "--stages", ALL_PASS])

    def test_bad_stage_rejected(self):
        with self.assertRaises(SystemExit):
            self.record("r1", "orchestrator=maybe")


class Progress(Base):
    def row(self, **kw):
        return self.summary(**kw)["actions"][0]

    def test_clean_run_and_counts(self):
        self.record("r1")
        row = self.row()
        self.assertTrue(row["clean_run"])
        self.assertEqual((row["clean_runs"], row["clean_runs_required"]), (1, 5))
        self.assertEqual(row["mode"], "actionlist")
        self.assertIn("4 more clean run(s) (1/5) to unlock Autonomous", row["next_milestone"])

    def test_failing_stage_milestone(self):
        self.record("r1")
        self.record("r2", "orchestrator=pass,data=fail,analysis=pass,action=pass,defense=pass", "deploy", "m2")
        self.record("r3", ALL_PASS, "deploy", "m3")
        row = self.row(mission="m3")
        self.assertTrue(row["clean_run"])
        self.assertAlmostEqual(row["stage_rates"]["data"], 2 / 3)
        self.assertIn("Data 67% → 90% (≈7 more passing run(s))", row["next_milestone"])

    def test_failed_run_reports_failed_stages(self):
        self.record("r1", "orchestrator=pass,data=pass,analysis=pass,action=pass,defense=fail")
        text = self.summary(fmt=None)
        self.assertIn("No — failed: Defense/Audit", text)

    def test_autonomous_after_enough_clean_runs(self):
        for i in range(3):
            self.record("r%d" % i, ALL_PASS, "deploy", "m%d" % i, "T1")
        row = self.row(mission="m2", level="L2")
        self.assertEqual(row["mode"], "autonomous")
        self.assertIn("Autonomous unlocked", row["next_milestone"])

    def test_operator_ceiling_milestone(self):
        for i in range(5):
            self.record("r%d" % i, ALL_PASS, "deploy", "m%d" % i, "T2")
        row = self.row(mission="m4", level="L2")
        self.assertEqual(row["mode"], "actionlist")
        self.assertIn("operator certification L4 is required to run T2 autonomously", row["next_milestone"])

    def test_t4_never_autonomous(self):
        self.record("r1", ALL_PASS, "rotate-keys", "m", "T4")
        row = self.row(level="L7")
        self.assertEqual(row["mode"], "actionlist")
        self.assertIn("never becomes autonomous", row["next_milestone"])

    def test_operator_below_floor(self):
        self.record("r1", ALL_PASS, "deploy", "m", "T3")
        self.assertIn("certification L4 or above is required for T3", self.row(level="L2")["next_milestone"])

    def test_mode_always_matches_gate_check(self):
        for i, stages in enumerate([ALL_PASS, "orchestrator=pass,data=fail,analysis=pass,action=pass,defense=pass",
                                    ALL_PASS, ALL_PASS, ALL_PASS, ALL_PASS]):
            self.record("r%d" % i, stages, "deploy", "m%d" % i, "T1")
            for level in range(1, 8):
                row = self.row(mission="m%d" % i, level="L%d" % level)
                self.assertEqual(row["mode"], gate_check.evaluate(self.action(), level)["verdict"])

    def test_operator_level_is_never_assumed(self):
        self.record("r1")
        with self.assertRaises(SystemExit):
            with contextlib.redirect_stdout(io.StringIO()):
                maturity.main(["summary", "--registry", self.reg, "--mission", "m"])
        with open(os.path.join(self.dir, ".actionboard", "config.json"), "w", encoding="utf-8") as fh:
            json.dump({"operator_level": "L3"}, fh)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            maturity.main(["summary", "--registry", self.reg, "--mission", "m", "--json"])
        self.assertEqual(json.loads(out.getvalue())["operator_level"], 3)


class Markdown(Base):
    def test_section_has_every_required_column(self):
        self.record("r1")
        text = self.summary(fmt=None)
        self.assertTrue(text.startswith("## Maturity & Progress Summary\n"))
        header = next(line for line in text.splitlines() if line.startswith("| Action"))
        for col in ("Orchestrator", "Data", "Analysis", "Action", "Defense/Audit", "Clean Run",
                    "Clean runs", "Execution mode", "Next milestone"):
            self.assertIn(col, header)
        self.assertIn("Guided → **Actionlist** → Autonomous", text)
        rows = [line for line in text.splitlines() if line.startswith("|")]
        self.assertEqual(len({line.count("|") for line in rows}), 1)  # aligned table

    def test_one_row_per_assignment_of_the_same_action(self):
        self.record("m-3", "orchestrator=pass,data=fail,analysis=pass,action=pass,defense=pass")
        self.record("m-5", "orchestrator=pass,data=pass,analysis=pass,action=fail,defense=pass")
        rows = self.summary()["actions"]
        self.assertEqual([r["run_id"] for r in rows], ["m-3", "m-5"])
        self.assertEqual([r["clean_run"] for r in rows], [False, False])
        self.assertIn("run `m-3`", rows[0]["name"])

    def test_empty_mission_still_renders_section(self):
        text = self.summary(mission="nothing", fmt=None)
        self.assertIn("No actions were scored in this mission", text)


if __name__ == "__main__":
    unittest.main()
