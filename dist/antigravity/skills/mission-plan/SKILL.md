---
name: mission-plan
description: Write an ActionBoard V5 Mission Plan (Agent Assignments, Skills Gap, Risk Register) as Markdown + compiled JSON-LD.
---

> Paths written `<skill-dir>/...` are relative to the directory that contains this SKILL.md.

# Mission Plan — Markdown + Knowledge Graph

Emits the second of the three ActionBoard V5 mission documents: what each Agent will do, what the
mission cannot yet do, and what could go wrong.

**Full prose, always.** This document is never compressed. Terse output and graph summaries do not
apply here, even when they are enabled for the mission. Write in full, clear, standard prose,
keep every table, column, field, and markdown structure intact, and do not shorten, merge, or omit
any section to save tokens. After writing, list the paths under `Files created/changed:`.

Format spec (read only if inspecting or extending the graph): `<skill-dir>/../actionboard-kb/references/mission-knowledge-format.md`.

## What a plan contains

| Section | Markdown form | Graph node |
|---------|---------------|-----------|
| Agent Assignments | Table: Agent → Task → Files Owned → Depends On → Acceptance | `Action` per row |
| Skills Gap | Table: Capability → Status → Notes | `DefinedTerm` per row |
| Risk Register | Table: Category → Risk → Severity → Mitigation | `Thing` (`additionalType: "Risk"`) per row |

## Procedure

1. **Reuse the mission slug** from `mission-brief.jsonld` (never re-derive it).
2. **Draft assignments** with exclusive file ownership (no two assignments own the same path) and observable acceptance criteria. Omit idle Agents.
3. **Run Skills Gap** via `skills-registry/actions-map.json`: `covered`, `use-existing-skill:<name>`, or `needs-new-skill` (conditional entries count as covered only when their `requires` precondition is met).
4. **Build the Risk Register** across `technical`, `scope`, `integration`, `data-loss` with severity `L`/`M`/`H` and a mitigation for every risk.
5. **Write `mission-plan.md`** with the three tables (`## Agent Assignments`, `## Skills Gap`, `## Risk Register`).
6. **Compile `mission-plan.jsonld` deterministically** (never hand-author JSON-LD):

   ```sh
   python <skill-dir>/../mission-report/scripts/compile_jsonld.py plan \
     --md <mission-dir>/mission-plan.md \
     --brief <mission-dir>/mission-brief.jsonld \
     --out <mission-dir>/mission-plan.jsonld
   ```

   This reuses `urn:voltron:mission:{slug}`, emits `PotentialActionStatus` assignments, updates `member`/`subjectOf`, and validates every `@id`.
7. **Report both paths**, present the three tables, and stop at the go/no-go gate:

> "Mission ready. Reply **go** to dispatch Agents, **no-go** to revise, or **edit <section>**."

Do not dispatch Red, Blue, or Yellow Agent before approval.
