---
name: skills-registry
description: ActionBoard V5 AgentFormation skills registry and actions map. Use during Skills Gap analysis (Step 4 of the mission flow) to map mission capabilities to registered action types, responsible Agents, and required tools/skills. Also use when the user asks "what can the Agents do", "list actionboard-v5 actions", or "show the actions map".
---

# ActionBoard V5 AgentFormation — Skills Registry

The registry is the single source of truth for **which Agent handles which action type** and **what tools or skills that action requires**. It is backed by the machine-readable actions map co-located with this skill:

```
skills/skills-registry/actions-map.json
```

## How to use this registry (Black Agent — Step 4)

During Skills Gap analysis:

1. Read `{{skill_dir}}/actions-map.json` ({{tool:read}}).
2. For each capability the mission needs, find the closest matching `action` entry:
   - **Exact or close match found, `status: "covered"`** → classify the capability as `covered`, cite the responsible Agent from the entry.
   - **Match found with non-empty `skills` list** → classify as `use-existing-skill <name>` using the first skill in the list; the responsible Agent invokes it.
   - **Match found with `requires` field** → the capability is conditionally covered. Surface the requirement (e.g., per-site user approval for `live-browser-action`) in the Skills Gap table Notes column.
   - **No match** → classify as `needs-new-skill` and propose a one-line description.
3. When a new skill is scaffolded mid-mission ({{tool:skill_creator}}), append a new entry to the actions map in your Mission Summary so the user can commit it (the installed copy of `actions-map.json` is read-only at runtime — registry updates ship with the next ActionBoard version).

## Actions map schema

Each entry in `actionTypes`:

| Field | Meaning |
|-------|---------|
| `action` | Kebab-case action type identifier (e.g., `api-integration`) |
| `agent` | The responsible Agent agent (`red-agent`, `blue-agent`, `green-agent`, `yellow-agent`, or `black-agent`) |
| `description` | One line: what this action type covers |
| `requiredTools` | Capabilities the Agent needs, named by their Claude Code tool names (`Read`, `Write`, `Edit`, `Bash`, `WebFetch`, ...). Each CLI maps them to its own tools; see the Agent's Tool glossary |
| `skills` | Skills the Agent invokes for this action (empty = built-ins suffice) |
| `requires` | Optional precondition outside this action (e.g., per-site approval, or a prior document) |
| `status` | `covered` \| `conditional` \| `experimental` |

## Answering "what can the Agents do"

When the user asks directly, render the actions map as a table grouped by Agent:
Agent → Action types → What it needs. Keep it under 30 lines; link to `actions-map.json` for the full data.

## Registering a new action type

New action types are added by editing `actions-map.json` in `src/skills/skills-registry/` of the ActionBoard Agent Formation repository, bumping `src/VERSION`, rebuilding, and reinstalling. An entry MUST name exactly one responsible Agent — if an action seems to need two Agents, split it into two entries with a `dependsOn` note in the description.
