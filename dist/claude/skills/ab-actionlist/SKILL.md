---
name: ab-actionlist
description: Create, read, update, and delete ActionLists and action items on an ActionBoard board. Use for "ab-actionlist", "add an action list", "list my action lists", "add an action item", or "mark this action done".
---

# ActionBoard ActionLists and action items

An ActionList is a titled list on a board; action items are the entries inside it.

All commands use `${CLAUDE_PLUGIN_ROOT}/skills/mission-report/scripts/submit_mission.py` (Python 3.9+, standard
library only). On Windows use `py` instead of `python`. The Pod and Board come from the project
config (`.actionboard/config.json`); pass `--board <id>` to override. Add `--no-input --json` when
you run commands, because an agent session cannot prompt.

If a command says you are not signed in, or no Pod or Board is selected, follow the ab-login skill
first.

## Rules

- Before any `delete`, show the user the target (id and title) and get their explicit yes in the
  conversation. Only then re-run it with `--yes`. Without `--yes` and with `--no-input`, delete
  refuses and changes nothing.
- Create commands are not idempotent: running one twice makes two records.
- Never print tokens or Authorization values.

## ActionLists

```sh
python ${CLAUDE_PLUGIN_ROOT}/skills/mission-report/scripts/submit_mission.py actionlist list --no-input --json [--status S] [--limit N] [--next-token T]
python ${CLAUDE_PLUGIN_ROOT}/skills/mission-report/scripts/submit_mission.py actionlist show <id> --no-input --json
python ${CLAUDE_PLUGIN_ROOT}/skills/mission-report/scripts/submit_mission.py actionlist create --title "TEXT" --no-input --json [--status S] [--context TEXT] [--notes TEXT] [--tags a,b] [--important] [--urgent] [--due ISO] [--start ISO]
python ${CLAUDE_PLUGIN_ROOT}/skills/mission-report/scripts/submit_mission.py actionlist update <id> --no-input --json [same optional fields, plus --title]
python ${CLAUDE_PLUGIN_ROOT}/skills/mission-report/scripts/submit_mission.py actionlist status <id> <STATUS> --no-input --json
python ${CLAUDE_PLUGIN_ROOT}/skills/mission-report/scripts/submit_mission.py actionlist delete <id> --no-input --json [--yes]
```

## Action items

```sh
python ${CLAUDE_PLUGIN_ROOT}/skills/mission-report/scripts/submit_mission.py action list --list <listId> --no-input --json [--status S ...]
python ${CLAUDE_PLUGIN_ROOT}/skills/mission-report/scripts/submit_mission.py action get <id> --no-input --json
python ${CLAUDE_PLUGIN_ROOT}/skills/mission-report/scripts/submit_mission.py action create --list <listId> --item "TEXT" --no-input --json [--status S] [--prompt TEXT] [--notes TEXT] [--tags a,b] [--important] [--urgent] [--due ISO] [--start ISO]
python ${CLAUDE_PLUGIN_ROOT}/skills/mission-report/scripts/submit_mission.py action update <id> --no-input --json [same optional fields, plus --item]
python ${CLAUDE_PLUGIN_ROOT}/skills/mission-report/scripts/submit_mission.py action status <id> <STATUS> --no-input --json
python ${CLAUDE_PLUGIN_ROOT}/skills/mission-report/scripts/submit_mission.py action delete <id> --no-input --json [--yes]
```

Status values: `New`, `Todo`, `Active`, `In_Progress`, `Done`, `AutoActionAiAgent`,
`ActionAssistAgent`.

`actionlist show` pages through the board's lists because the server has no single-get. The list
output has no reliable total count; follow `nextToken` for more.
