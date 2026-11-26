---
name: ab-signup
description: Create an ActionBoard account from the CLI, then sign in. Use for "ab-signup", "sign up for ActionBoard", "create an ActionBoard account", or "I don't have an ActionBoard account".
---

> Paths written `<skill-dir>/...` are relative to the directory that contains this SKILL.md.

# ActionBoard Sign-up

Helps someone with no ActionBoard account pick a region, create the account in the browser, and
then sign in to the plugin through the existing login.

All commands use `<skill-dir>/../mission-report/scripts/submit_mission.py` (Python 3.9+,
standard library only). On Windows use `py` instead of `python`.

You run inside an agent session with no interactive terminal, so the script cannot prompt.
Ask the user in the conversation and pass their answers as flags, exactly as below.

## Step 1 — Check the current state

```sh
python <skill-dir>/../mission-report/scripts/submit_mission.py status --json
```

If `logged_in` is `true`, say which `email` is signed in and ask whether they still want a new
account. If not, stop and point them to the ab-login skill.

## Step 2 — Ask the region first

Ask: "Which region is your account for? Bangladesh (`bd`) or United States (`us`, plugin sign-in
not available yet)?"

## Step 3 — Open the sign-up page

```sh
python <skill-dir>/../mission-report/scripts/submit_mission.py signup --region <bd|us> --no-input --json
```

- `us` returns `"status": "region_pending"` and exits non-zero. Opening nothing is expected. Give
  the user the `signup_url`, explain that plugin sign-in for those accounts is not available yet,
  offer `bd` if it fits them, and stop.
- `bd` returns `"opened"`. If it is `false`, give the user the `signup_url` to open themselves.

## Step 4 — The user creates the account

Tell the user to create the account and verify their email in the browser tab. Wait until they say
the email is verified.

**Never ask for or accept the password or the verification code in this conversation.** If they
paste one, tell them not to share it here and do not repeat it.

## Step 5 — Existing session

If Step 1 showed a signed-in account, confirm that signing in with the new account replaces that
session before continuing.

## Step 6 — Sign in

Follow the ab-login skill from its Step 2 (browser login), then its Pod and Board steps. If
`pods --no-input --json` returns no Pods, explain that missions need a Pod, so the account must
join or create one before it can submit missions.

## Security rules

- Never commit `.actionboard/credentials.json` or `~/.actionboard/credentials.json`.
- Tokens are kept in the OS keychain; run `logout` to remove them.
- Never print tokens, the password, or the verification code.
