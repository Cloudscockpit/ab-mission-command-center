# Mission Report — Regional ActionBoard sign-up from the plugin

- **Mission ID:** `regional-actionboard-signup-from-plugin`
- **Brief:** [mission-brief.md](mission-brief.md) · **Plan:** [mission-plan.md](mission-plan.md) · **Dashboard:** [mission-report.html](mission-report.html)
- **Started:** 2026-11-25T21:39:18Z · **Ended:** 2026-11-26T15:35:50Z
- **Branch:** `feat/ab-signup` from base commit `0ce9f63f8e9f427104fb9f9039fcedee1693140c`. Nothing has been committed or pushed.
- **Operator level:** L4 (from `.actionboard/config.json`)

## Outcome

| ID | Agent | Assignment | Outcome |
|---|---|---|---|
| A1 | Blue Agent | Region check using public pages only | **Shipped.** BD sign-ups create accounts in the plugin's own Cognito pool; US could not be established. |
| A2 | Blue Agent | Regional sign-up flow in `auth.py` and `common.py` | **Shipped** after one rework round (A2b). |
| A3 | Red Agent | `signup` command, `ab-signup` skill, docs, changelog, `dist/` | **Shipped** after a re-plan (A3b, two more docs) and one fix round (A3c, two Medium defects). |
| A4 | Yellow Agent | Tests, all CI suites, security review | **Shipped.** 34 new tests; all six suites pass; every finding resolved or accepted. |

The plugin now has a `signup` command and an `ab-signup` skill. The user chooses a region first. Choosing Bangladesh (`bd`) opens `https://actionboard.com.bd/auth/signup` and then hands over to the existing browser login. Choosing United States (`us`) opens nothing and explains that plugin sign-in for US accounts is not available yet, with the `https://actionboard.ai/auth/signup` link. The plugin never accepts a password or verification code.

## Mission Log

Entries are in dispatch order and summarise each Agent's own report.

**Green Agent, recon (before approval; no assignment in the plan).** The plugin had no sign-up support and no GraphQL operation that creates an account or a Pod. The edge proxy, login site, and backend source were not in this repository. In the operator-supplied `ab-marketing` source it found `auth_register`, `auth_confirmAccount`, `auth_resendConfirmationCode`, and `pods_createPod`, but no free or trial tier, and noted that the client supplies `ownerId` to `pods_createPod`. These findings led the operator to defer trial Pod creation and to require a region choice.

**A1, Blue Agent — done.** `GET https://actionboard.com.bd/auth/signup` and `GET https://actionboard.ai/auth/signup` both returned 200 and are working sign-up pages. `GET https://actionboard.com.bd/api/auth/social/Google` returned 307 to `absaas-dev.auth.ap-southeast-1.amazoncognito.com/oauth2/authorize` with the plugin's client ID and callback Lambda, so BD accounts are the plugin's accounts. `GET https://actionboard.ai/api/auth/social/Google` (and `/LinkedIn`) returned 200 with an HTML shell instead of a redirect, so the US pool is not established. `ab-marketing` has no `/cli` route, and its `region.ts` switches only the site URL, currency, payment gateway, and pre-order flag; Cognito settings come from per-deployment environment variables. Blue's report gave the client ID suffix as `0070`; the actual suffix is `ir70`. The same-or-different verdict was correct. Files changed: none.

**Operator decision after A1.** BD ships working; US stays selectable but marked pending.

**A2, Blue Agent — done.** Added `SIGNUP_REGIONS` and `SIGNUP_REGION_CHOICES` to `common.py`, and `signup_url`, `SignupRegionPending`, `_signup_region`, and `open_signup_page` to `auth.py`. Smoke checks: `bd`, `BD`, and `" bd "` all give the BD URL; `eu`, an empty string, and `None` raise `ValueError` naming `bd` and `us`; `us` raises `SignupRegionPending` without calling the browser. Existing `tests/report` modules passed when run one by one (186 tests). Blue reported that a full `discover -s tests/report` run stalled for more than eight minutes; Yellow Agent later could not reproduce this on either the base commit or the working tree (186 tests in about 20 seconds). Files changed: `actionboard_cli/auth.py`, `actionboard_cli/common.py`.

**A3, Red Agent — done.** Added the `signup` subcommand and `cmd_signup`, moved `cmd_login`'s browser branch into a shared `_browser_login` helper with unchanged behaviour, re-exported the new names from `submit_mission.py`, created `src/skills/ab-signup/SKILL.md`, pointed `ab-login` to it, and updated `cli-reference.md`, `README.md`, and `CHANGELOG.md` (under `## Unreleased`, no version bump). `build.py --check` was clean; `tests/build` 23 and `tests/guard` 32 passed. Red could not exercise the interactive terminal path, which needs a real terminal and account.

**A3b, Red Agent — done (re-plan).** Black Agent found two more files that send users without a login to `ab-login` and added them to Red's ownership: a new "ActionBoard Sign-up" row in `src/agents/black-agent.md` and a clause in `src/skills/submit-mission/SKILL.md`. `dist/` rebuilt.

**A4, Yellow Agent — first run.** Wrote 34 tests in `tests/report/test_signup.py`. Three failed on real defects: Ctrl+C at the region prompt and EOF or Ctrl+C at the replace-session prompt produced tracebacks. Findings: two Medium (those defects) and three Low (`--json` in a terminal skips the login prompt; the browser call caught only `webbrowser.Error`; extra blank lines and import order).

**A3c, Red Agent and A2b, Blue Agent — done (fix round).** Red guarded both prompts inside `cmd_signup` without changing the shared `prompt_choice`; all three cancel paths return 1 and leave credentials untouched. Blue widened the browser catch to `(webbrowser.Error, OSError)` and fixed the spacing. Red rebuilt `dist/`.

**A4, Yellow Agent — final run, done.** All six CI suites pass; `build.py --check` prints `dist/ is up to date`. Findings 1, 2, 4, and 5 are fixed; finding 3 is accepted as designed. Yellow also reproduced A1's evidence independently: BD 307 to the plugin's Cognito domain, client ID (suffix `ir70`), and callback host; US 200 with an HTML shell; `common.py` sets `plugin_login` to `True` for `bd` and `False` for `us`. Files changed: `tests/report/test_signup.py` (new).

**Black Agent verification.** Re-ran Yellow's exact commands, `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/<suite> -v`, for each suite, plus `python3 scripts/build.py --check`. The results matched Yellow's report: guard 32 OK, build 23 OK, install 55 OK (1 skipped), maturity 18 OK, report 220 OK (1 skipped), installer 23 OK, and `dist/ is up to date`.

**Board sync.** The operator chose to sync this mission to the board "Actionboard Mission Board" using this repository's 1.3.1 CLI. The `IN_PROGRESS` sync at mission start failed with "not logged in to ActionBoard": the access token had expired an hour after sign-in and automatic renewal failed. No progress lines were posted. The final submit waits for the operator to sign in again.

## Success Criteria

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | The region is always the user's choice | **Met** | `test_signup.py` covers `--no-input` without `--region` (non-zero exit, error naming `bd` and `us`) and the interactive region prompt; the `report` suite passed 220 tests in Black Agent's re-run. |
| 2 | The right page opens and the user ends signed in | **Partly met** | Met for `bd`: tests assert the browser is called once with exactly `https://actionboard.com.bd/auth/signup`, and that the interactive path calls the shared `_browser_login` once with no provider, which the existing `test_browser_login` tests cover end to end against a mocked server. The `us` half was changed by the operator's decision: `us` deliberately opens nothing and reports `region_pending` with the exact US URL, which is tested. No real sign-up was performed. |
| 3 | No password or verification code passes through the plugin | **Met** | A parser-introspection test asserts that `signup` has no option containing password, code, email, url, or host; Yellow's security review found no path that accepts, prompts for, logs, or echoes either, and `ab-signup/SKILL.md` forbids them in chat. |
| 4 | A region the plugin cannot log in to is not presented as working | **Met** | Yellow independently reproduced A1's evidence (BD same pool, client, and callback; US not established) and confirmed `SIGNUP_REGIONS` sets `plugin_login` to `True` for `bd` and `False` for `us`. |
| 5 | The build stays clean | **Met** | Black Agent's re-run: all six suites OK and `dist/ is up to date`. |

## Deferred

| Item | Reason |
|---|---|
| Trial AI Pod creation | Out of scope by the operator's decision; planned for a later mission. Carry forward: `pods_createPod` takes `podName`, `tierId`, and a client-supplied `ownerId`; no free or trial `tierId` was found; whether the server checks `ownerId` against the caller is not established. |
| Enabling the US region | US accounts' Cognito pool is not established. Enabling it is a one-line change to `plugin_login` once whoever runs the US deployment confirms it uses the `absaas-dev` pool in `ap-southeast-1`; a different pool would need per-region Cognito settings and server support. |
| A real end-to-end sign-up | Not performed by design (no real accounts during the mission). The interactive terminal path is covered only by mocked tests. |
| Version bump and release | Out of scope. The changelog entry sits under `## Unreleased`. |
| Commit and pull request | Not requested. All changes are uncommitted on `feat/ab-signup`. |

## Follow-ups found during the mission

These are outside this mission's scope and were not changed.

| Severity | Finding | Where |
|---|---|---|
| H | Access-token renewal failed twice today, each time right after the token expired, so users may have to sign in again every hour. The cause is hidden because `ensure_main_token` swallows the renewal error. | `src/skills/mission-report/scripts/actionboard_cli/auth.py` (`ensure_main_token`) |
| H | Default Cognito names say `absaas-dev`, and the site's social-login callback is a development Lambda used by every environment. | `common.py` defaults; `ab-marketing` `docs/social-login.md` |
| M | `status` reports `logged_in: true` whenever any refresh token exists, even one the server rejects. | `commands.py` (`cmd_status`) |
| M | The installed plugin 1.3.0 uploads mission files to `actionboard-kb-agent` when a default AWS profile exists, instead of the Pod's bucket; fixed in 1.3.1. | Installed plugin 1.3.0 |
| M | In `ab-marketing`, `/auth/login?redirect=` is passed to `router.push` without validation, and a `console.log` in `src/app/auth/login/page.tsx` logs a one-time session key. | `ab-marketing` |
| L | EOF at the region prompt exits 2 while Ctrl+C exits 1; harmless but inconsistent. | `commands.py` (`cmd_signup`) |

## Maturity & Progress Summary

Mission `regional-actionboard-signup-from-plugin` · Operator L4 · Scoring window: last 20 runs within 90 days · Source: `.actionboard/registry.json` via `gate_check.py`.

Stage cells show this run's result, then the stage's pass rate across the scoring window.

| Action | Tier (threshold) | Orchestrator | Data | Analysis | Action | Defense/Audit | Clean Run | Clean runs | Execution mode | Next milestone |
|---|---|---|---|---|---|---|---|---|---|---|
| External CLI integration, run `regional-actionboard-signup-from-plugin-1` (`api-integration`) | T2 (≥90%) | ✅ pass · 100% | ❌ fail · 80% | ✅ pass · 60% | ✅ pass · 40% | ❌ fail · 80% | No — failed: Data, Defense/Audit | 0/5 | Guided → **Actionlist** → Autonomous | Raise Action 40% → 90% (≈16 more passing run(s)); Analysis 60% → 90% (≈15 more passing run(s)); Data 80% → 90% (≈5 more passing run(s)); Defense/Audit 80% → 90% (≈5 more passing run(s)), then reach 5 clean runs to unlock Autonomous. |
| External CLI integration, run `regional-actionboard-signup-from-plugin-2` (`api-integration`) | T2 (≥90%) | ✅ pass · 100% | ✅ pass · 80% | ❌ fail · 60% | ✅ pass · 40% | ✅ pass · 80% | No — failed: Analysis | 0/5 | Guided → **Actionlist** → Autonomous | Raise Action 40% → 90% (≈16 more passing run(s)); Analysis 60% → 90% (≈15 more passing run(s)); Data 80% → 90% (≈5 more passing run(s)); Defense/Audit 80% → 90% (≈5 more passing run(s)), then reach 5 clean runs to unlock Autonomous. |
| Tests and live verification (`test-authoring`) | T2 (≥90%) | ✅ pass · 86% | ✅ pass · 86% | ✅ pass · 86% | ✅ pass · 57% | ✅ pass · 100% | Yes | 2/5 | Guided → **Actionlist** → Autonomous | Raise Action 57% → 90% (≈15 more passing run(s)); Orchestrator 86% → 90% (≈3 more passing run(s)); Data 86% → 90% (≈3 more passing run(s)); Analysis 86% → 90% (≈3 more passing run(s)), then reach 5 clean runs to unlock Autonomous. |
| Plugin code changes (`code-implementation`) | T3 (≥95%) | ❌ fail · 71% | ✅ pass · 100% | ❌ fail · 71% | ❌ fail · 57% | ✅ pass · 86% | No — failed: Orchestrator, Analysis, Action | 2/10 | Guided → **Actionlist** → Autonomous | Raise Action 57% → 95% (≈18 more passing run(s)); Orchestrator 71% → 95% (≈15 more passing run(s)); Analysis 71% → 95% (≈18 more passing run(s)); Defense/Audit 86% → 95% (≈13 more passing run(s)), then reach 10 clean runs to unlock Autonomous. |

**Scoring evidence.** A1: Data failed because the US Cognito settings could not be obtained; Defense/Audit failed because the reported client ID suffix was wrong. A2: Analysis failed because a rework round was needed. A3: Orchestrator failed because Black Agent's plan missed two files and needed a re-plan; Analysis and Action failed because two Medium defects needed a second attempt (recorded with `--retried`). A4: all stages passed, with Action verified by Black Agent's re-run of Yellow's exact commands. All four runs share one session ID, so they are not independent evidence for promotion. Green Agent's recon had no plan assignment and was not scored.

## Files created/changed

- `src/skills/mission-report/scripts/actionboard_cli/auth.py`
- `src/skills/mission-report/scripts/actionboard_cli/common.py`
- `src/skills/mission-report/scripts/actionboard_cli/commands.py`
- `src/skills/mission-report/scripts/submit_mission.py`
- `src/skills/ab-signup/SKILL.md` (new)
- `src/skills/ab-login/SKILL.md`
- `src/skills/submit-mission/SKILL.md`
- `src/skills/submit-mission/references/cli-reference.md`
- `src/agents/black-agent.md`
- `README.md`
- `CHANGELOG.md`
- `tests/report/test_signup.py` (new)
- `dist/` (regenerated by `scripts/build.py` for the Claude, Codex, Antigravity, and OpenCode targets)
- `.actionboard/registry.json` (four scored runs appended)
- `.actionboard/preferences.json` (git-ignored; terse output enabled)
- `.graphifyignore` (new) and `graphify-out/` (git-ignored)
- `docs/missions/2026-11-25-regional-actionboard-signup-from-plugin/mission-brief.md`, `mission-brief.jsonld`, `mission-plan.md`, `mission-plan.jsonld`, `mission-report.md`, `mission-report.jsonld`, `mission-metrics.json`, `mission-report.html`
- `.actionboard/config.json` was already modified before the mission by the Pod and Board selection, and is not part of the feature.
