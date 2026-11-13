---
name: ab-login
description: Log the user in to ActionBoard from the CLI and choose the Pod and Board that missions are submitted to. Use when the user runs "ab-login", asks to "log in to ActionBoard", "connect my ActionBoard account", "switch pod", or "switch board", and whenever a mission submit or fetch reports that the user is not logged in or has no Pod/Board selected.
---

> Paths written `<skill-dir>/...` are relative to the directory that contains this SKILL.md.

# ActionBoard Login, Pod and Board Selection

Signs the user in once, then saves the Pod and Board that `submit-mission` and `fetch-mission`
use. Tokens are cached and renewed automatically, so the user logs in again only when the
refresh token itself expires.

All commands use `<skill-dir>/../mission-report/scripts/submit_mission.py` (Python 3.9+,
standard library only). On Windows use `py` instead of `python`.

You run inside an agent session with no interactive terminal, so the script cannot prompt.
Ask the user in the conversation and pass their answers as flags, exactly as below.

## Step 1 — Check the current state

```sh
python <skill-dir>/../mission-report/scripts/submit_mission.py status --json
```

- `connection` is `edge` by default: calls go through the ActionBoard edge proxy and no API key
  or AWS key is needed. Do not ask the user for one.
- `logged_in` is `true`: skip to Step 3.
- `logged_in` is `false`: continue with Step 2.

## Step 2 — Log in

Ask the user for their ActionBoard email and password. Tell them the alternative first: they can
run `python <skill-dir>/../mission-report/scripts/submit_mission.py login` in their own terminal,
which prompts there and keeps the password out of this conversation.

If they give you the password, pass it through the environment, never as a flag:

```sh
ACTIONBOARD_PASSWORD='<password>' python <skill-dir>/../mission-report/scripts/submit_mission.py login --email <email>
```

Never repeat the password back, write it to a file, or include it in a report. If login fails,
show the script's error and ask again; do not guess.

## Step 3 — Choose the Pod

```sh
python <skill-dir>/../mission-report/scripts/submit_mission.py pods --no-input --json
```

Show the user the pod names and ask which one to use. If there is exactly one pod, use it and
say so. Keep the chosen `podId`.

## Step 4 — Choose the Board

```sh
python <skill-dir>/../mission-report/scripts/submit_mission.py boards --pod <podId> --no-input --json
```

Show the user the board names and ask which one to use. If there is exactly one board, use it
and say so.

## Step 5 — Save the selection

```sh
python <skill-dir>/../mission-report/scripts/submit_mission.py select --pod <podId> --board <boardId>
```

This writes `pod_id` and `board_id` to `.actionboard/config.json`. Confirm to the user which
account, Pod and Board are now active.

## Step 6 — Mission sync (optional)

Ask the user how missions should reach this board, and save the answer:

- `ask` (default): Black Agent asks once per mission.
- `auto`: every mission syncs its status, Agent progress, and final report without asking.
- `off`: never sync; the user submits by hand.

```sh
python <skill-dir>/../mission-report/scripts/submit_mission.py select --sync <ask|auto|off>
```

## Security rules

- Never commit `.actionboard/credentials.json` or `~/.actionboard/credentials.json`.
- Never print tokens or the password.
