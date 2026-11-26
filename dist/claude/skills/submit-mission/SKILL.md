---
name: submit-mission
description: Submit ActionBoard Mission Brief, Plan, and Report from the CLI to a Pod Board. Use when asked to submit, upload, or push a mission.
---

# Submit Mission to ActionBoard Pod & Board

Uploads a mission's Brief, Plan, Report, JSON-LD graphs, metrics, and HTML dashboard to an ActionBoard Pod's Board via `${CLAUDE_PLUGIN_ROOT}/skills/mission-report/scripts/submit_mission.py` (Python 3.9+, stdlib only; on Windows use `py`).

By default every call uses the ActionBoard edge proxy (no API key or AWS keys required). Direct AppSync/AWS configuration details live in `${CLAUDE_PLUGIN_ROOT}/skills/submit-mission/references/cli-reference.md`.

## Step-by-step execution

Inside an agent session (non-interactive), always run `status --json` first. If `logged_in` is `false`, or `default_pod_id` / `default_board_id` is empty, run `${CLAUDE_PLUGIN_ROOT}/skills/ab-login/SKILL.md` first (if they have no ActionBoard account yet, use the ab-signup skill first), then run `submit --no-input`.

### 1. Check status & select Pod/Board (if needed)

```sh
python ${CLAUDE_PLUGIN_ROOT}/skills/mission-report/scripts/submit_mission.py status --json
python ${CLAUDE_PLUGIN_ROOT}/skills/mission-report/scripts/submit_mission.py pods
python ${CLAUDE_PLUGIN_ROOT}/skills/mission-report/scripts/submit_mission.py boards --pod <podId-or-slug>
python ${CLAUDE_PLUGIN_ROOT}/skills/mission-report/scripts/submit_mission.py select --pod <podId-or-slug> --board <boardId-or-name>
```

### 2. Submit the mission

```sh
# Auto-detect latest mission in docs/missions/ or actionboard-v5-missions/
python ${CLAUDE_PLUGIN_ROOT}/skills/mission-report/scripts/submit_mission.py submit --no-input

# Explicit directory, pod, or board
python ${CLAUDE_PLUGIN_ROOT}/skills/mission-report/scripts/submit_mission.py submit \
  --mission-dir docs/missions/<YYYY-MM-DD-slug> \
  --pod <podId-or-slug> \
  --board <boardId-or-name>
```

Files land in the board's File Manager under `Missions/<mission-name>/` (the root `Missions` folder is reused; nested folders such as `case-files/` are preserved). Re-submitting is idempotent: unchanged files are skipped and changed CLI files replace their previous version without touching human-uploaded files (pass `--keep-old` to retain old versions).

Key flags: `--dry-run`, `--mission-id <id>`, `--invitation-id <id>`, `--create-mission`, `--update-mission`, `--phase <name>` / `--milestone <name>` (group files under `Missions/<mission-name>/<name>/`), `--status <INITIATED|IN_PROGRESS|COMPLETED|FAILED|ARCHIVED>`, `--skip-s3`, `--keep-old`, `--json`.

### 3. Live progress & sync mode (optional)

```sh
python ${CLAUDE_PLUGIN_ROOT}/skills/mission-report/scripts/submit_mission.py progress \
  --mission-dir docs/missions/<YYYY-MM-DD-slug> --status IN_PROGRESS --comment "Red Agent: done — API client shipped"

python ${CLAUDE_PLUGIN_ROOT}/skills/mission-report/scripts/submit_mission.py select --sync auto
```

`select --sync <ask|auto|off>` controls automatic board sync (`ask` default). Never include secrets, tokens, or file contents in progress comments.

## Security rules

- Never commit `.actionboard/credentials.json` or raw API keys/passwords; keep credential files `0600`.
- Never ask for the user's password in chat; use browser sign-in (`login`).
