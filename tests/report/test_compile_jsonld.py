"""Tests for deterministic Markdown -> schema.org JSON-LD compiler (compile_jsonld.py)."""

import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS_DIR = os.path.join(ROOT, "src", "skills", "mission-report", "scripts")
sys.path.insert(0, SCRIPTS_DIR)

import compile_jsonld  # noqa: E402
import render_dashboard  # noqa: E402


SAMPLE_BRIEF_MD = """# Mission Brief — Add Health Endpoint

## Objective

Expose a GET /health endpoint returning service status and version.

## Scope

- Add `src/health.py` with a status handler.
- Register the route in `src/app.py`.

## Out of Scope

- Authentication or rate limiting.

## Success Criteria

- `GET /health` returns HTTP 200 with JSON `{"status": "ok"}`.

## Constraints

- Standard library only.
"""

SAMPLE_PLAN_MD = """# Mission Plan — Add Health Endpoint

## Agent Assignments

| Agent | Task | Files Owned | Depends On | Acceptance |
|---|---|---|---|---|
| Red Agent | Implement health handler | `src/health.py`, `src/app.py` | none | GET /health returns 200 |
| Yellow Agent | Write health endpoint tests | `tests/test_health.py` | assignment:1 | Unit tests pass |

## Skills Gap

| Capability | Status | Notes |
|---|---|---|
| HTTP routing | covered | code-implementation |

## Risk Register

| Category | Risk | Severity | Mitigation |
|---|---|---|---|
| Technical | Route conflict | L | Verify existing routes before wiring |
"""

SAMPLE_REPORT_MD = """# Mission Report — Add Health Endpoint

## Outcome

| Agent | Task | Status | Summary |
|---|---|---|---|
| Red Agent | Implement health handler | shipped | Added GET /health returning ok and version. |
| Yellow Agent | Write health endpoint tests | blocked | Fixture database port was busy. |

## Maturity & Progress Summary

Recorded in `.actionboard/registry.json`.
"""


class TestCompileJsonLd(unittest.TestCase):
    def test_brief_plan_report_roundtrip_and_dashboard_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            mdir = os.path.join(tmp, "2026-11-19-add-health-endpoint")
            os.makedirs(mdir)
            brief_md = os.path.join(mdir, "mission-brief.md")
            plan_md = os.path.join(mdir, "mission-plan.md")
            report_md = os.path.join(mdir, "mission-report.md")
            brief_ld = os.path.join(mdir, "mission-brief.jsonld")
            plan_ld = os.path.join(mdir, "mission-plan.jsonld")
            report_ld = os.path.join(mdir, "mission-report.jsonld")
            reg_path = os.path.join(tmp, "registry.json")

            for p, content in ((brief_md, SAMPLE_BRIEF_MD), (plan_md, SAMPLE_PLAN_MD), (report_md, SAMPLE_REPORT_MD)):
                with open(p, "w", encoding="utf-8") as fh:
                    fh.write(content)

            with open(reg_path, "w", encoding="utf-8") as fh:
                json.dump({
                    "registry_version": "1",
                    "actions": [
                        {
                            "id": "code-implementation",
                            "name": "Code implementation",
                            "risk_tier": "T2",
                            "runs": [
                                {
                                    "run_id": "add-health-endpoint-1",
                                    "mission": "add-health-endpoint",
                                    "stages": {
                                        "orchestrator": True,
                                        "data": True,
                                        "analysis": True,
                                        "action": True,
                                        "defense": True,
                                    },
                                    "first_attempt": True,
                                    "provenance": "scored",
                                }
                            ],
                        }
                    ],
                }, fh)

            self.assertEqual(compile_jsonld.main(["brief", "--md", brief_md, "--out", brief_ld]), 0)
            self.assertEqual(compile_jsonld.main(["plan", "--md", plan_md, "--brief", brief_ld, "--out", plan_ld]), 0)
            self.assertEqual(
                compile_jsonld.main(["report", "--md", report_md, "--plan", plan_ld, "--registry", reg_path, "--out", report_ld]),
                0,
            )
            self.assertEqual(compile_jsonld.main(["validate", mdir]), 0)

            with open(report_ld, encoding="utf-8") as fh:
                rep_data = json.load(fh)
            actions = [n for n in rep_data["@graph"] if n.get("@type") == "Action"]
            self.assertEqual(len(actions), 2)
            self.assertEqual(actions[0]["actionStatus"], "https://schema.org/CompletedActionStatus")
            self.assertEqual(actions[1]["actionStatus"], "https://schema.org/FailedActionStatus")
            self.assertIn("Fixture database port", actions[1]["error"])

            maturity_nodes = [n for n in rep_data["@graph"] if n.get("additionalType") == "MaturityProgress"]
            self.assertEqual(len(maturity_nodes), 1)
            self.assertEqual(maturity_nodes[0]["name"], "code-implementation")

            # Verify compiled report renders cleanly through render_dashboard.py
            html_out = os.path.join(mdir, "mission-report.html")
            rc = render_dashboard.main([
                "render",
                "--report", report_ld,
                "--mission", "add-health-endpoint",
                "--registry", reg_path,
                "--operator-level", "L4",
                "--out", html_out,
            ])
            self.assertEqual(rc, 0)
            self.assertTrue(os.path.isfile(html_out))
            self.assertGreater(os.path.getsize(html_out), 1000)

    def test_validate_rejects_unresolved_reference_and_bad_status(self):
        bad = {
            "@context": "https://schema.org",
            "@graph": [
                {
                    "@type": "Action",
                    "@id": "urn:voltron:mission:x:assignment:1",
                    "agent": {"@id": "urn:voltron:lion:purple"},
                    "actionStatus": "https://schema.org/UnknownStatus",
                    "object": [{"@id": "urn:voltron:file:missing.py"}],
                }
            ],
        }
        errs = compile_jsonld.validate_jsonld(bad)
        self.assertTrue(any("actionStatus" in e for e in errs))
        self.assertTrue(any("agent URN" in e for e in errs))
        self.assertTrue(any("unresolved @id" in e for e in errs))


if __name__ == "__main__":
    unittest.main()
