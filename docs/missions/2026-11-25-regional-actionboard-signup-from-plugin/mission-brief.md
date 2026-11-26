# Mission Brief — Regional ActionBoard sign-up from the plugin

**Objective:** Let a person with no ActionBoard account choose a region, sign up on that region's ActionBoard site from the Claude plugin, and end up signed in to the plugin.

- **Mission ID:** `regional-actionboard-signup-from-plugin`
- **Date:** 2026-11-25
- **Repository:** `ab-mission-command-center`, branch `feat/ab-signup`, base commit `0ce9f63f`
- **Requested by the operator:** "User can sign up for actionboard.ai from the Claude plugin … using ActionBoard Cognito auth sign-up". The operator then narrowed it: ask the user which region to register in first and use that region's domain, and defer trial AI Pod creation to a later mission.

## Scope

1. A `signup` command in the ActionBoard CLI that takes a region choice, `us` (`https://actionboard.ai`) or `bd` (`https://actionboard.com.bd`), and opens that site's `/auth/signup` page in the user's browser.
2. After the user has signed up and verified their email, the command runs the existing browser login so the user ends signed in, with tokens stored exactly as `login` stores them.
3. A new `ab-signup` skill that asks the user which region they want before anything else, then runs the command; the `ab-login` skill points new users to it.
4. Unit tests, plus updates to the CLI reference, the README, and the changelog.
5. A regenerated `dist/` for the Claude, Codex, Antigravity, and OpenCode targets.

## Out of Scope

1. Creating a trial AI Pod. This is deferred to a later mission; the recon findings about `pods_createPod` carry forward to it.
2. Changes to the `ab-marketing` site, the edge proxy, the ActionBoard backend, or the Cognito user pools.
3. Paid tiers, payment, and billing.
4. A version bump or a release.
5. The known `status` bug that reports a session as logged in whenever any refresh token exists.
6. Creating a real ActionBoard account during the mission.

## Success Criteria

1. **The region is always the user's choice.** With `--no-input` and no `--region`, the command exits with a non-zero status and an error that names `us` and `bd`. Checked by a unit test.
2. **The right page opens and the user ends signed in.** `signup --region us` opens exactly `https://actionboard.ai/auth/signup` and `signup --region bd` opens exactly `https://actionboard.com.bd/auth/signup`; the command then completes the existing login against a mocked server and stores the tokens. Checked by unit tests with a mocked browser and a mocked HTTP opener.
3. **No password or verification code passes through the plugin.** The `signup` command has no password or code option and never prompts for either. Checked by a unit test and by Yellow Agent's security review.
4. **A region the plugin cannot log in to is not presented as working.** The command's behaviour per region matches Blue Agent's A1 verdict on whether that region's accounts are the ones the plugin logs in to. Checked by Yellow Agent against the A1 evidence.
5. **The build stays clean.** Every test suite passes and `python3 scripts/build.py --check` reports no drift. Checked by Yellow Agent running both commands and reporting the exact counts.

## Constraints

1. The CLI targets Python 3.9 or newer, uses the standard library only, and must run on Windows, macOS, and Linux.
2. `src/` is the canonical source and `dist/` is generated from it by `scripts/build.py` (ADR-0001); nobody edits `dist/` by hand.
3. Work happens on the branch `feat/ab-signup`. Nothing is committed or pushed unless the operator asks.
4. Passwords and verification codes are entered only in the browser, never in the chat or the CLI.
5. Assumption: the two regions are the ones defined in `ab-marketing`'s `src/shared/config/region.ts`, `us` and `bd`.
6. Assumption: the chosen region is saved only if A1 shows that login needs to know it.
7. The operator's uncommitted changes to `.actionboard/config.json` and `.graphifyignore` stay out of the feature.
