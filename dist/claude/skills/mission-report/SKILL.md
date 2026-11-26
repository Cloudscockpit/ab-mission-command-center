---
name: mission-report
description: Write the ActionBoard V5 Mission Report (Markdown, compiled JSON-LD graph, maturity summary, metrics, HTML dashboard) after Agents finish.
---

# Mission Report — Markdown + Compiled Knowledge Graph

Emits the third and final ActionBoard V5 mission document: every assignment outcome recorded against
the plan's graph nodes, plus maturity scores, `mission-metrics.json`, and `mission-report.html`.

**Full prose, always.** This document is never compressed. Terse output and graph summaries do not
apply here, even when they are enabled for the mission. Write in full, clear, standard prose,
keep every table, column, field, and markdown structure intact, and do not shorten, merge, or omit
any section to save tokens. After writing, list the paths under `Files created/changed:`.

Detailed rubric and dashboard notes live in `${CLAUDE_PLUGIN_ROOT}/skills/mission-report/references/reporting-guide.md`. Format
spec lives in `${CLAUDE_PLUGIN_ROOT}/skills/actionboard-kb/references/mission-knowledge-format.md`.

## Required sections

| Section | Content |
|---------|---------|
| Outcome | Table: Agent → Task → Status (`shipped` / `blocked` / `deferred`) → Summary |
| Mission Log | Each Agent's report in dispatch order |
| Success Criteria | Each brief criterion marked met or unmet, with concrete evidence |
| Deferred | What was cut and why |
| `## Maturity & Progress Summary` | Mandatory 5-stage score table and autonomy verdict from `maturity.py` |

## Procedure

1. **Score and record maturity** for every dispatched assignment using its registry action type from
   `skills-registry/actions-map.json` (rubric in `references/reporting-guide.md`). On an action's
   first run, classify its risk tier via `${CLAUDE_PLUGIN_ROOT}/skills/actionboard-devops-mission/references/risk-classification.md`:

   ```sh
   python ${CLAUDE_PLUGIN_ROOT}/skills/actionboard-devops-mission/scripts/maturity.py record \
     --registry .actionboard/registry.json --mission <slug> \
     --action <action-type> --run-id <slug>-<assignment-n> --mode <guided|actionlist|formation> \
     --stages orchestrator=pass,data=pass,analysis=pass,action=pass,defense=pass \
     [--retried] [--target <cli>] [--notes "<evidence summary>"]
   ```

   Render and paste the section verbatim into `mission-report.md`:

   ```sh
   python ${CLAUDE_PLUGIN_ROOT}/skills/actionboard-devops-mission/scripts/maturity.py summary \
     --registry .actionboard/registry.json --mission <slug>
   ```

2. **Write `mission-report.md`** in full prose, including the `## Maturity & Progress Summary`
   section (even if no action was scored — explain why). Check success criteria against evidence,
   not assignment status.

3. **Compile `mission-report.jsonld` deterministically** (never hand-author JSON-LD):

   ```sh
   python ${CLAUDE_PLUGIN_ROOT}/skills/mission-report/scripts/compile_jsonld.py report \
     --md <mission-dir>/mission-report.md \
     --plan <mission-dir>/mission-plan.jsonld \
     --registry .actionboard/registry.json \
     --out <mission-dir>/mission-report.jsonld
   ```

   This reuses every `@id` from `mission-plan.jsonld`, sets `endDate`, transitions `actionStatus`,
   adds `MaturityProgress` nodes, and validates the graph automatically.

4. **Write `mission-metrics.json` and render `mission-report.html`** (on Windows use `py`):

   ```sh
   python ${CLAUDE_PLUGIN_ROOT}/skills/mission-report/scripts/render_dashboard.py metrics \
     --out <mission-dir>/mission-metrics.json --mission <slug> \
     --started-at <start-iso-utc> --ended-at <now-iso-utc> --git-base <base-commit> \
     --test "<suite-name>,<test-command>,<passed>,<failed>,<skipped>"

   python ${CLAUDE_PLUGIN_ROOT}/skills/mission-report/scripts/render_dashboard.py render \
     --report <mission-dir>/mission-report.jsonld --mission <slug> \
     --out <mission-dir>/mission-report.html \
     --registry .actionboard/registry.json \
     --metrics <mission-dir>/mission-metrics.json [--operator-level <L1-L7>]
   ```

   Report any render failure, or any line containing `WARNING` on stderr, in the Mission Summary. Include
   `mission-report.md`, `mission-report.jsonld`, `mission-metrics.json`, `mission-report.html`, and
   `.actionboard/registry.json` in `Files created/changed:`.

5. **Submit to ActionBoard Pod & Board** (when board sync is on or requested): call the
   `ab_submit_mission` MCP tool with `mission_dir: <mission-dir>` (see the `submit-mission` skill).
