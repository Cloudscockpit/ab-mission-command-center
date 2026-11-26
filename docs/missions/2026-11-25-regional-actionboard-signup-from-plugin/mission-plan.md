# Mission Plan — Regional ActionBoard sign-up from the plugin

- **Mission ID:** `regional-actionboard-signup-from-plugin`
- **Brief:** [mission-brief.md](mission-brief.md)
- **Date:** 2026-11-25
- **Approved:** the operator replied "go" on 2026-11-25. Mission start 2026-11-25T21:39:18Z, base commit `0ce9f63f8e9f427104fb9f9039fcedee1693140c`.
- **Dispatch order:** A1, then A2, then A3, then A4. Each assignment uses the previous one's output, so they run in sequence. If A1 finds that either region's accounts differ from the ones the plugin logs in to, or cannot establish it, Black Agent stops and reports to the operator before A2 starts.

All CLI paths below are under `src/skills/mission-report/scripts/`.

## Agent Assignments

| ID | Agent | Task | Files Owned | Depends On | Acceptance |
|---|---|---|---|---|---|
| A1 | Blue Agent | Region check using public pages only. Load `/auth/signup` on `https://actionboard.ai` and `https://actionboard.com.bd`, and the plugin's `/cli` login page. Request each site's `/api/auth/social/Google` without following the redirect, and compare the Cognito domain and client ID in it with the plugin's defaults. | none | none | For each region, the report states whether the sign-up page works and whether its accounts are the same as the plugin's, different, or not established, with every request's URL and status code. No saved login is used and no form is submitted. |
| A2 | Blue Agent | Add a fixed list of regional sign-up addresses and the sign-up flow: open the chosen region's sign-up page, then run the existing browser login. | `actionboard_cli/auth.py`, `actionboard_cli/common.py` | A1 | Sign-up addresses come only from the fixed `us`/`bd` list, never from user input. Existing `login` behaviour and its tests are unchanged. Only regions A1 verified are offered as working. |
| A3 | Red Agent | Add the `signup` command and the `ab-signup` skill, link it from `ab-login`, update the docs and changelog, then regenerate `dist/` with `python3 scripts/build.py`. | `actionboard_cli/commands.py`, `submit_mission.py`, `src/skills/ab-signup/SKILL.md` (new), `src/skills/ab-login/SKILL.md`, `src/skills/submit-mission/references/cli-reference.md`, `README.md`, `CHANGELOG.md`, `dist/` | A2 | In a terminal the command asks for the region; with `--no-input` it requires `--region us` or `--region bd` and otherwise fails with an error naming both. `--json` output works. It asks before replacing an existing login. `python3 scripts/build.py --check` passes. |
| A4 | Yellow Agent | Write the tests, run every suite, and review the change for security. | `tests/report/test_signup.py` (new), `tests/report/test_browser_login.py` | A3 | Tests cover both regions, a missing region, an invalid region, a timeout, a bad nonce, and a declined replacement of an existing login. The report gives the exact test command and pass/fail counts, and security findings rated by severity. |

Green Agent completed recon before the plan was approved and has no assignment. No file appears in more than one assignment.

## Skills Gap

| Capability | Status | Notes |
|---|---|---|
| Regional site check | `covered` | Registry action `api-integration`, Blue Agent. Public GET requests only. |
| Sign-up flow in the CLI | `covered` | Registry action `api-integration`, Blue Agent. Reuses the existing local callback, nonce, and PKCE code in `auth.py`. |
| CLI command, skill file, and docs | `covered` | Registry actions `code-implementation` and `file-scaffolding`, Red Agent. |
| Building `dist/` | `covered` | `scripts/build.py`, run by Red Agent; CI runs `--check`. |
| Tests | `covered` | Registry action `test-authoring`, Yellow Agent. |
| Security review | `covered` | Registry action `security-review`, Yellow Agent. |
| Checking current Cognito behaviour | `covered` | Registry action `version-lookup`; its precondition is met because Context7 answered during preflight. |
| Real sign-up in a browser | `use-existing-skill:browser-actions` | Conditional on per-site approval, and the operator enters any credentials. Not part of this plan. |

No new skills are needed. The installed plugin's actions map (1.3.0) was used; it differs from the copy in this repository.

## Risk Register

| Category | Risk | Severity | Mitigation |
|---|---|---|---|
| Integration | A region's accounts live in a different Cognito pool, so a user signs up and then cannot log in through the plugin. The operator's Pods and the plugin's defaults point to the BD side. | H | A1 compares each region with the plugin's defaults before any code is written. If they differ or cannot be established, Black Agent stops and asks the operator. |
| Integration | A site hides its Cognito settings or blocks the check. | M | A1 reports "not established" instead of guessing, and the operator decides. |
| Integration | The default names say `absaas-dev`, and the site's social-login callback is a development Lambda in every environment, so real sign-ups may pass through development infrastructure. | H | Recorded for the operator to confirm before any release. |
| Integration | A new user may not have an ActionBoard profile or any Pod yet, so Pod selection finds nothing. | M | `signup` ends with a clear "no Pods yet" message instead of an error. |
| Integration | A stale `dist/` fails CI, because CI runs `build.py --check`. | M | Only Red Agent writes `dist/`, and only through `build.py`; Yellow Agent runs `--check`. |
| Technical | After email verification the site ends at its own login page and cannot hand control back to the plugin. | M | The plugin starts its own login after sign-up. The site's unvalidated `?redirect=` parameter is not used. |
| Technical | Email verification takes longer than the five-minute login wait. | M | The user can run `login` later to finish signing in, and the command says so. |
| Technical | A password or verification code reaches the chat, the CLI, or the logs. The site's `auth_register` operation takes a raw password. | H | The plugin never calls `auth_register`; sign-up happens only in the browser, and tests check that no password or code option exists. |
| Scope | New users have an account but cannot run missions until they have a Pod. | M | Accepted for this mission; the command's final message says so. |
| Scope | Trial Pod work creeps back into this mission. | L | Out of scope by the operator's decision. The recon findings (`pods_createPod`, no free tier found, no verified `ownerId` check) are carried to the later mission. |
| Data-loss | Signing up replaces the saved login of the person already signed in. | M | The command detects an existing session and asks before replacing it; with `--no-input` it refuses unless told to replace. |
| Data-loss | Board sync from the installed plugin 1.3.0 would upload files to the wrong S3 bucket. | H | Board sync for this mission runs the repository's 1.3.1 CLI, which uploads through the edge proxy to the Pod's bucket. |
