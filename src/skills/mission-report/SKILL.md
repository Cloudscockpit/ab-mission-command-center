---
name: mission-report
description: Write a ActionBoard V5 Mission Report recording what each Agent shipped, blocked on, or deferred, as Markdown plus a schema.org JSON-LD knowledge graph. Use when the user asks to "write the mission report", "summarize the mission", "what shipped", or after Agents report back at the end of the ActionBoard V5 mission flow, and whenever a report must be exported as structured or machine-readable output.
---

# Mission Report — Markdown + Knowledge Graph

Emits the third and final ActionBoard V5 mission document: the outcome of every assignment, recorded
against the same graph nodes the plan created.

{{partial:full_prose_rule}}

**Read the format reference first:** `{{skills_root}}/actionboard-kb/references/mission-knowledge-format.md`.
The report's value depends entirely on reusing the plan's identifiers — a report that mints
fresh `@id`s records nothing, because nothing links back to what was promised.

## What a report contains

| Section | Content | Graph effect |
|---------|---------|-------------|
| Outcome | One line per assignment: shipped / blocked / deferred | `Action.actionStatus` transition |
| Mission Log | Each Agent's report verbatim-ish, in dispatch order | `Action.result` / `Action.error` |
| Success Criteria | Each brief criterion marked met or unmet, with evidence | `DefinedTerm` + evidence |
| Deferred | What was cut, and why | `Action` left `Potential`, with a reason |
| **Maturity & Progress Summary** (mandatory) | Per dispatched assignment: the 5-stage score breakdown, Clean Run status, autonomy progress (tier, clean runs `3/5`, execution mode Guided → Actionlist → Autonomous), and the next milestone | `Thing` (`additionalType: "MaturityProgress"`) per assignment, `about` the assignment |

## Procedure

1. **Load the plan's graph.** Read `mission-plan.jsonld` and reuse every `@id` — mission,
   assignments, Agents, files. The report does not create assignments; it resolves them.
2. **Transition each assignment's status** using the KB's `actionStatus` vocabulary:
   Agent reported `done` → `CompletedActionStatus`; Agent reported `blocked` →
   `FailedActionStatus` plus an `error` string naming the blocker; never dispatched →
   left at `PotentialActionStatus` with a `result` explaining the deferral.
3. **Record results honestly.** `result` carries what the Agent actually produced. If a Agent
   reported `done` but its acceptance criterion was never checked, that is not
   `CompletedActionStatus` — mark it `Active` and say the verification is outstanding.
4. **Check success criteria against evidence**, not against assignment status. An assignment
   can complete while its criterion still fails. Cite the evidence — a command's output, a
   test result, a file that now exists — for each criterion marked met.
5. **Set `endDate`** on the mission node.
6. **Score and record maturity.** Every mission counts toward the project's AI-ops maturity.
   For each assignment that was dispatched (done or blocked; never-dispatched work is not scored):
   1. **Name the action.** Use the assignment's registry action type from the `skills-registry`
      skill's `actions-map.json` (for example `code-implementation`, `api-integration`,
      `test-authoring`), so the same kind of work accumulates history across missions.
   2. **Score the five stages pass or fail, with one line of evidence each.** A stage you cannot
      score is a fail. Never round up.

      | Stage | Pass when |
      |---|---|
      | Orchestrator | The assignment, its file ownership, and its dispatch order were right for the goal; no ownership conflict or re-plan was needed |
      | Data | The inputs (recon, files, upstream outputs) were located, current, and complete |
      | Analysis | The approach the Agent took was correct for the goal; no rework was needed |
      | Action | The acceptance criterion was met on the first attempt and verified by someone other than the Agent that did the work (normally Yellow Agent) |
      | Defense/Audit | No policy or guard violation, no High security finding, no unlogged side effect, and the Agent's `Files created/changed:` list matches what actually changed |

   3. **Record the run** in the project's registry (`.actionboard/registry.json`, committed as
      evidence). On an action's first run, classify its risk tier with
      `{{skills_root}}/actionboard-devops-mission/references/risk-classification.md` and pass
      `--name`, `--risk-tier`, and `--end-condition`:

      ```sh
      python {{skills_root}}/actionboard-devops-mission/scripts/maturity.py record \
        --registry .actionboard/registry.json --mission <slug> \
        --action <action-type> --run-id <slug>-<assignment-n> --mode <guided|actionlist|formation> \
        --stages orchestrator=pass,data=pass,analysis=pass,action=pass,defense=pass \
        [--retried] [--target <cli>] [--notes "<evidence summary>"]
      ```

      Use `--retried` when the work only went green on a second attempt. On Windows use `py`.
   4. **Render the section** and paste it into the report verbatim:

      ```sh
      python {{skills_root}}/actionboard-devops-mission/scripts/maturity.py summary \
        --registry .actionboard/registry.json --mission <slug>
      ```

      The operator's certified maturity level (L1-L7) comes from `.actionboard/config.json`
      (`"operator_level"`) or from asking the user. Never assume it and never raise it: missions
      raise an action's maturity, not the operator's. If the user will not give a level, keep the
      section with the stage table and write "Execution mode: not computed (operator level not
      provided)".
7. **Write `mission-report.md`**, then `mission-report.jsonld`. The Markdown must contain a
   `## Maturity & Progress Summary` section with the table from step 6, even when no action was
   scored (say why). Add one `MaturityProgress` node per scored assignment (see the KB). Validate
   per the KB checklist and report both paths, plus `.actionboard/registry.json`.

## Writing rules

- Report what happened, not what was supposed to happen. A mission where two of five
  assignments blocked is a useful record; a report that rounds it to "mission complete" is
  not, and the graph will contradict it.
- Every `FailedActionStatus` needs an `error` a reader can act on. "Failed" alone is noise.
- Do not quietly drop an assignment that was never dispatched. Deferred work stays in the
  graph with its reason, or the next mission rediscovers it as new.
- Keep the Markdown readable: lead with the Outcome table so a reader gets the result in thirty
  seconds. Never shorten or omit a required section to get there; the full-prose rule above wins.
- The maturity numbers come only from `maturity.py`, which uses the same rules as the formation
  gate. Do not compute or adjust them by hand.

## What the accumulated graph answers

Because Agent and file identifiers are global across missions (see the KB's identifier scheme),
a directory of mission reports answers questions no single report can: which files block most
often, which Agent's assignments most frequently need a second pass, which success criteria
keep recurring unmet. Mention this to the user once they have more than one mission on disk —
it is the reason the format exists.
