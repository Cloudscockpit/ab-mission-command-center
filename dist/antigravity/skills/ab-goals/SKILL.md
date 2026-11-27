---
name: ab-goals
description: Create, read, update, and delete Goals on an ActionBoard board. Use for "ab-goals", "add a goal", "list my goals", "set a goal to completed", or "change a goal's priority".
---

> Paths written `<skill-dir>/...` are relative to the directory that contains this SKILL.md.

# ActionBoard Goals

All commands use `<skill-dir>/../mission-report/scripts/submit_mission.py` (Python 3.9+, standard
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

## Commands

```sh
python <skill-dir>/../mission-report/scripts/submit_mission.py goal list --no-input --json [--status S]
python <skill-dir>/../mission-report/scripts/submit_mission.py goal get <id> --no-input --json
python <skill-dir>/../mission-report/scripts/submit_mission.py goal create --title "TEXT" --priority P --no-input --json [--description TEXT] [--status S] [--due ISO] [--start ISO] [--user-id ID]
python <skill-dir>/../mission-report/scripts/submit_mission.py goal update <id> --no-input --json [--title] [--priority] [--description] [--status] [--due] [--start]
python <skill-dir>/../mission-report/scripts/submit_mission.py goal status <id> <STATUS> --no-input --json
python <skill-dir>/../mission-report/scripts/submit_mission.py goal delete <id> --no-input --json [--yes]
```

Status values: `PENDING`, `IN_PROGRESS`, `COMPLETED`. Priority values: `LOW`, `MEDIUM`, `HIGH`.

`goal list` shows up to 100 goals and warns on stderr if more exist, because server-side paging is
not available. `--status` filters on the client. A new goal belongs to the signed-in user unless
`--user-id` is given.
