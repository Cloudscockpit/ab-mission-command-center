---
name: ab-login
description: Log the user in to ActionBoard from the CLI and choose the Pod and Board that missions are submitted to. Use when the user runs "ab-login", asks to "log in to ActionBoard", "connect my ActionBoard account", "switch pod", or "switch board", and whenever a mission submit or fetch reports that the user is not logged in or has no Pod/Board selected.
---

# ActionBoard Login, Pod and Board Selection

Signs the user in once, then saves the Pod and Board that `submit-mission` and `fetch-mission`
use. Tokens are cached and renewed automatically, so the user logs in again only when the
refresh token itself expires.

All commands use `${CLAUDE_PLUGIN_ROOT}/skills/mission-report/scripts/submit_mission.py` (Python 3.9+,
standard library only). On Windows use `py` instead of `python`.

You run inside an agent session with no interactive terminal, so the script cannot prompt.
Ask the user in the conversation and pass their answers as flags, exactly as below.

## Step 1 — Check the current state

```sh
python ${CLAUDE_PLUGIN_ROOT}/skills/mission-report/scripts/submit_mission.py status --json
```

- `connection` is `edge` by default: calls go through the ActionBoard edge proxy and no API key
  or AWS key is needed. Do not ask the user for one.
- `logged_in` is `true`: skip to Step 3.
- `logged_in` is `false`: continue with Step 2.

## Step 2 — Log in through the browser

Run the login yourself. It opens the ActionBoard sign-in page in the user's browser and waits up
to five minutes:

```sh
python ${CLAUDE_PLUGIN_ROOT}/skills/mission-report/scripts/submit_mission.py login
```

Tell the user: "Sign in to ActionBoard in the browser tab that just opened (email and password,
Google, or LinkedIn). If no tab opened, open the link printed above." The command finishes
by itself once they sign in. Add `--provider Google` (or `LinkedIn`) when the user says
which one they use.

**Never ask for the password in this conversation.** The browser sign-in keeps it out of the CLI
and out of the chat. If browser sign-in cannot work (for example on a remote machine over SSH,
where the browser cannot reach this machine's localhost), ask the user to run
`python ${CLAUDE_PLUGIN_ROOT}/skills/mission-report/scripts/submit_mission.py login --email <email>` in their
own terminal, which prompts for the password there.

If login fails, show the script's error and offer to run it again; do not guess.

## Step 3 — Choose the Pod

```sh
python ${CLAUDE_PLUGIN_ROOT}/skills/mission-report/scripts/submit_mission.py pods --no-input --json
```

Show the user the pod names and ask which one to use. If there is exactly one pod, use it and
say so. Keep the chosen `podId`.

## Step 4 — Choose the Board

```sh
python ${CLAUDE_PLUGIN_ROOT}/skills/mission-report/scripts/submit_mission.py boards --pod <podId> --no-input --json
```

Show the user the board names and ask which one to use. If there is exactly one board, use it
and say so.

## Step 5 — Save the selection

```sh
python ${CLAUDE_PLUGIN_ROOT}/skills/mission-report/scripts/submit_mission.py select --pod <podId> --board <boardId>
```

This writes `pod_id` and `board_id` to `.actionboard/config.json`. Confirm to the user which
account, Pod and Board are now active.

## Step 6 — Mission sync (optional)

Ask the user how missions should reach this board, and save the answer:

- `ask` (default): Black Agent asks once per mission.
- `auto`: every mission syncs its status, Agent progress, and final report without asking.
- `off`: never sync; the user submits by hand.

```sh
python ${CLAUDE_PLUGIN_ROOT}/skills/mission-report/scripts/submit_mission.py select --sync <ask|auto|off>
```

## Security rules

- Never commit `.actionboard/credentials.json` or `~/.actionboard/credentials.json`.
- Tokens are kept in the OS keychain (macOS Keychain, Windows Credential Manager, or the Linux
  Secret Service); `status` shows where. Run `logout` to remove them.
- Never print tokens or the password.
