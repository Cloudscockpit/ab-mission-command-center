---
name: ab-files
description: List, upload, download, and delete ActionBoard board files and folders. Use for "ab-files", "upload a file to my board", "download a file from ActionBoard", "list board files", or "make a folder on the board".
---

> Paths written `<skill-dir>/...` are relative to the directory that contains this SKILL.md.

# ActionBoard board files

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
- Downloads write only into the `--out` directory and refuse to replace an existing file unless
  `--overwrite` is given. Uploads read only the local path you name.

## Commands

```sh
python <skill-dir>/../mission-report/scripts/submit_mission.py files folders --no-input --json
python <skill-dir>/../mission-report/scripts/submit_mission.py files mkdir "NAME" --no-input --json [--parent <folderId>]
python <skill-dir>/../mission-report/scripts/submit_mission.py files list --folder <folderId> --no-input --json
python <skill-dir>/../mission-report/scripts/submit_mission.py files upload <path> --folder <folderId> --no-input --json [--note TEXT] [--tags a,b]
python <skill-dir>/../mission-report/scripts/submit_mission.py files download <fileId> --no-input --json [--out DIR] [--overwrite]
python <skill-dir>/../mission-report/scripts/submit_mission.py files delete <fileId> --no-input --json [--yes]
```

Run `files folders` first to find the folder id to upload into.
