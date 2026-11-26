---
name: ab-login
description: Log in to ActionBoard and select a Pod and Board through the ActionBoard MCP tools. Use for "ab-login", login/pod/board switching, or "Not logged in" errors from submit or fetch.
---

# ActionBoard Login, Pod and Board Selection

Signs the user in once, then saves the Pod and Board that `submit-mission` and `fetch-mission`
use. Everything goes through the `actionboard` MCP server's `ab_*` tools, which ActionBoard
configures on install. Tokens are cached and renewed automatically, so the user logs in again only
when the refresh token itself expires.

If no `ab_*` tools are available, the `actionboard` MCP server is not running: tell the user it
needs [uv](https://docs.astral.sh/uv/) (`uvx`) and a restart of this agent session, then stop.

## Step 1: Check the current state

Call `ab_auth_status`.

- `logged_in` is `true`: skip to Step 3.
- `logged_in` is `false`: continue with Step 2.

## Step 2: Log in through the browser

First tell the user: "A browser tab will open. Sign in to ActionBoard there (email and password,
Google, or LinkedIn)." Then call `ab_login`. It waits up to five minutes and returns once they have
signed in. Pass `provider: "Google"` or `"LinkedIn"` when the user says which one they use.

**Never ask for the password in this conversation.** `ab_login` takes none: the password stays in
the browser. If login fails or times out, show the error and offer to try again; do not guess.

Over SSH or on a headless machine no local browser can open: ask the user to connect with
`ssh -L 3000:localhost:3000 -L 3001:localhost:3001 <host>`, run `ab login` there, and open the printed link locally.

## Step 3: Choose the Pod

Call `ab_list_pods`. Show the pod names and ask which one to use. If there is exactly one pod,
use it and say so. Keep the chosen `podId`.

## Step 4: Choose the Board

Call `ab_list_boards` with that `pod_id`. Show the board names and ask which one to use. If there is
exactly one board, use it and say so.

## Step 5: Save the selection and the sync mode

Ask the user how missions should reach this board:

- `ask` (default): Black Agent asks once per mission.
- `auto`: every mission syncs its status, Agent progress, and final report without asking.
- `off`: never sync; the user submits by hand.

Call `ab_select_board` with `pod_id`, `board_id`, and `sync`. It writes the selection to
`.actionboard/config.json`. Confirm which account, Pod, Board and sync mode are now active.

## Security rules

- Never commit `.actionboard/credentials.json` or `~/.actionboard/credentials.json`.
- Tokens are kept in the OS keychain when one exists; `ab_auth_status` shows where (`token_store`).
  `ab_logout` removes them.
- The tools never return tokens. Never print a token or a password.
