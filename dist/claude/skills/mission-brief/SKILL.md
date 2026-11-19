---
name: mission-brief
description: Write an ActionBoard V5 Mission Brief (Markdown + compiled JSON-LD) at Step 1 or when scoping a mission.
---

# Mission Brief — Markdown + Knowledge Graph

Emits the first of the three ActionBoard V5 mission documents in both human and machine form.

**Full prose, always.** This document is never compressed. Terse output and graph summaries do not
apply here, even when they are enabled for the mission. Write in full, clear, standard prose,
keep every table, column, field, and markdown structure intact, and do not shorten, merge, or omit
any section to save tokens. After writing, list the paths under `Files created/changed:`.

Format spec (read only if inspecting or extending the graph): `${CLAUDE_PLUGIN_ROOT}/skills/actionboard-kb/references/mission-knowledge-format.md`.

## What a brief contains

| Section | Content | Graph node |
|---------|---------|-----------|
| Objective | One sentence. What the mission achieves, not how. | `Project.description` |
| Scope | Bulleted, concrete, each item independently checkable. | `ItemList` of `DefinedTerm` |
| Out of Scope | What a reader might reasonably assume is included but isn't. | `ItemList` of `DefinedTerm` |
| Success Criteria | Observable, testable. "Returns 200", not "works well". | `DefinedTerm` per criterion |
| Constraints | Assumptions, deadlines, tech limits, things held fixed. | `ItemList` of `DefinedTerm` |

## Procedure

1. **Derive the slug** from the objective: kebab-case, drop articles, truncate to 48 chars. Fix it now and never change it mid-mission.
2. **Confirm the output directory** with the user — default `./actionboard-v5-missions/{date}-{slug}/`. Ask before creating a top-level directory in someone's repo.
3. **Write `mission-brief.md`** in full prose: H1 title, then the five sections (`## Objective`, `## Scope`, `## Out of Scope`, `## Success Criteria`, `## Constraints`). Keep it under a page.
4. **Compile `mission-brief.jsonld` deterministically** (never hand-author JSON-LD):

   ```sh
   python ${CLAUDE_PLUGIN_ROOT}/skills/mission-report/scripts/compile_jsonld.py brief \
     --md <mission-dir>/mission-brief.md \
     --out <mission-dir>/mission-brief.jsonld \
     --slug <slug>
   ```

   This builds the schema.org `Project`, `Report`, and `ItemList`/`DefinedTerm` nodes and validates every `@id` reference automatically.
5. **Report both paths** to the user and state that the brief is Step 1 of 3.

## Writing rules

- If the objective is vague, ask ONE clarifying question before drafting.
- Every success criterion must name how it is checked; otherwise move it to Scope.
- Out of Scope is required; state assumptions explicitly in Constraints.
