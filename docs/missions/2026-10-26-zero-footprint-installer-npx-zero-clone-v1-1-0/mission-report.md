# Mission Report — Zero-Footprint Installer and NPX Zero-Clone Package (v1.1.0)

Mission: `urn:voltron:mission:zero-footprint-installer-npx-zero-clone-v1-1-0` · Report date: 2026-10-26 · Status: **closed** (closed by the user on 2026-10-26; npm publish and tag deferred to the next session) · Operator level: L4

## Outcome

The git-clone one-liner now cleans up after itself with `--cleanup`, uninstall no longer needs the clone, and a new npx/uvx wrapper installs from a release bundle in the OS temp directory, so Codex, Antigravity and OpenCode installs leave nothing in the project but the CLI's own directories. Live smoke runs on all three CLIs proved it, after one uninstall defect (D1) was found and fixed. All six assignments are complete. CI on pull request #1 is green on all 16 jobs across Windows, macOS and Linux after two Python 3.9 fixes. The npx command will not work for anyone until v1.1.0 is tagged and published, which the user will do in the next session.

| # | Agent | Assignment | Status | Result |
|---|---|---|---|---|
| 1 | Green | Environment and release recon | Completed | Recon delivered: codex 0.164.0 (logged in), agy 1.4.7, opencode 2.1.4, Node 24.16, uv 0.11.21, Python only via `py -3`. npm not logged in and @actionboard scope unconfirmed; no tags or releases; codeload tarballs public. Listed every clone dependency in scripts/install.py with line numbers. |
| 2 | Red | Self-cleaning installer and clone-free uninstall | Completed | `--cleanup` (opt-in) removes the clone only when it is a strict subdirectory of the project with the expected origin, a clean tree, no unpushed commits, no stash and no ignored files other than __pycache__. Uninstall logic moved to the standard-library scripts/actionboard_uninstall.py, which is copied next to the manifest. Two follow-up rounds: guard hardening from the security review, and D1 (uninstall left runtime __pycache__) from live smoke. Verified on a real `git clone --depth 1` from GitHub. |
| 3 | Blue | npx and uvx zero-clone wrappers | Completed | packages/installer (@actionboard/install 1.1.0, zero dependencies) and packages/installer-py (uvx from the git subdirectory) download the tagged tarball over HTTPS into a temp dir, extract safely, run install.py with a persistent Python and always delete the temp dir. release.yml publishes only when NPM_TOKEN exists. Second round fixed a Medium symlink-chain escape in the legacy extractor (verified on Linux), skipped venv Pythons and closed error-path streams. |
| 4 | Yellow | Regression tests and security review | Completed | tests/install 55, tests/installer 23 (py) and 28+1 skipped (node) pass on Windows; Linux (WSL) also green. New tests fail against the 1.0.0 installer. CI gains an npx-installer job on three OSes. The first CI run on pull request #1 failed the Python 3.9 legs on all three OSes (HTTPError.close crash in the uvx wrapper); a local 3.9 run then exposed stale dist/ bytecode being installed. Both fixed in edb7a24; CI run 40230139567 is green on all 16 jobs across Windows, macOS and Linux. |
| 5 | Yellow | Live smoke runs on Codex, Antigravity and OpenCode | Completed | tests/smoke/results-2026-10-v1.1.md: six rows (three CLIs by one-liner and npx). Install, no-leftover, mission load and Context7 pass everywhere; guard passes (Codex via rules layer only, D2). Uninstall failed on four rows (D1); after Red's fix all four were retested and pass. D3 to D5 recorded. |
| 6 | Red | Release documentation and version bump | Completed | README makes npx the default for Codex, Antigravity and OpenCode with uvx and the --cleanup one-liner as fallbacks, keeps the manual checkout path, and states npx returns 'tag not published yet' until release. CHANGELOG 1.1.0 dated 2026-10-26. src/VERSION 1.1.0, dist/ regenerated, build --check clean, every manifest reads 1.1.0. |

## Mission Log

1. **Recon** found no tags, an unconfirmed npm scope, and that `install.py`'s uninstall was blocked only by a module-level `import build`.
2. **Red** built `--cleanup` and the standalone uninstaller.
3. **Blue** built the npx and uvx wrappers and the release workflow.
4. **Yellow** wrote the regression suites and a security review: a Medium symlink-chain escape in the legacy extractor (Blue fixed), cleanup could delete unpushed work (Red hardened), and the Node wrapper accepted venv Pythons (Blue fixed). Re-run green on Windows and Linux.
5. **Live smoke** on Codex, Antigravity and OpenCode passed install, no-leftover, mission load and Context7; uninstall left runtime `__pycache__` (D1) on four rows.
6. **Red** fixed D1 and wrote the release docs and version bump; **Yellow** added D1 regression tests and retested the four rows (all pass, no model calls).
7. **Black** re-ran every suite (Python suites OK, Node 37 pass and 1 skipped), confirmed a real GitHub shallow clone passes the cleanup guards, and recorded six scored runs.
8. **Release branch.** At the user's request: removed this mission's two smoke-run trust entries from ~/.codex/config.toml (backup kept), deleted next-plan.md, committed on release/v1.1.0-zero-footprint-installer and opened pull request #1.
9. **CI round 1** failed the Python 3.9 legs on all three OSes: the uvx wrapper's HTTPError.close() raises on 3.9 (Blue fixed). Running every suite on 3.9 locally then showed the installer copying stale dist/ __pycache__ into projects (Red fixed). Commit edb7a24; **CI round 2** green on all 16 jobs (run 40230139567).
10. **Mission closed** by the user.

Detail: `tests/smoke/results-2026-10-v1.1.md`.

## Success Criteria

No mission brief was written; these criteria come from the mission objective and deliverables.

| Criterion | Met? | Evidence |
|---|---|---|
| No clone folder left in the project for Codex, Antigravity and OpenCode | Met | Six live smoke installs left only the CLI's own directories and nothing in %TEMP%; ZeroLeftoverClone tests per target |
| Uninstall works without the clone | Met | Standalone uninstaller restored the pre-install listing on all six rows after the D1 fix; PycacheOnUninstall and StandaloneUninstaller tests |
| `npx @actionboard/install --target <cli> [--global]` installs from a temp-dir bundle | Partly | Works offline with ACTIONBOARD_BUNDLE on all three CLIs; not usable by anyone until v1.1.0 is tagged and the package is published |
| Regression tests for zero leftover clone folders | Met | tests/install 55 pass; new tests fail on 1.0.0 (36 failures/errors); CI run 40230139567 green on Windows, macOS and Linux, Python 3.9 to 3.12 |
| Live smoke runs on Codex, Antigravity and OpenCode | Met | tests/smoke/results-2026-10-v1.1.md, including the D1 retest |
| README, version 1.1.0, registry record, mission report | Met | README and CHANGELOG updated; build --check clean; six runs recorded in .actionboard/registry.json; this report |
| Backwards compatibility for manual git-clone installs | Met | --cleanup is opt-in; test asserts Claude output byte-identical without it; existing round-trip tests unchanged |

## Follow-ups

- Merge pull request #1 (https://github.com/Cloudscockpit/ab-mission-command-center/pull/1).
- `npm login`, confirm the @actionboard scope, add the NPM_TOKEN secret, then push tag v1.1.0 so release.yml publishes and creates the GitHub release. Until then npx and uvx print 'tag not published yet'.
- Pin bundle integrity (Medium, open): embed the release tarball's SHA-256 in the package and verify before extract.
- Codex live hook denial (carried from v1.0.0, D2): trust hooks with /hooks interactively, then try `openshell sandbox delete --all`.
- Codex Context7 discovery needs prompting (D3) and OpenCode shows a generic 'Permission denied: shell' (D4); both documented as known gaps.
- ~/.codex/config.toml still holds one scratch-project trust entry from an earlier session's smoke run (not this mission); this mission's two entries were removed.

## Maturity & Progress Summary

Mission `zero-footprint-installer-npx-zero-clone-v1-1-0` · Operator L4 · Scoring window: last 20 runs within 90 days · Source: `.actionboard/registry.json` via `gate_check.py`.

Stage cells show this run's result, then the stage's pass rate across the scoring window.

| Action | Tier (threshold) | Orchestrator | Data | Analysis | Action | Defense/Audit | Clean Run | Clean runs | Execution mode | Next milestone |
|---|---|---|---|---|---|---|---|---|---|---|
| Codebase and environment recon (`codebase-recon`) | T2 (≥90%) | ✅ pass · 100% | ✅ pass · 100% | ✅ pass · 100% | ✅ pass · 100% | ✅ pass · 100% | Yes | 2/5 | Guided → **Actionlist** → Autonomous | 3 more clean run(s) (2/5) to unlock Autonomous. |
| External CLI integration (`api-integration`) | T2 (≥90%) | ✅ pass · 100% | ✅ pass · 100% | ✅ pass · 100% | ❌ fail · 0% | ✅ pass · 100% | No — failed: Action | 0/5 | Guided → **Actionlist** → Autonomous | Raise Action 0% → 90% (≈18 more passing run(s)), then reach 5 clean runs to unlock Autonomous. |
| Tests and live verification, run `zero-footprint-installer-npx-zero-clone-v1-1-0-4` (`test-authoring`) | T2 (≥90%) | ✅ pass · 100% | ✅ pass · 75% | ✅ pass · 100% | ❌ fail · 50% | ✅ pass · 100% | No — failed: Action | 1/5 | Guided → **Actionlist** → Autonomous | Raise Action 50% → 90% (≈16 more passing run(s)); Data 75% → 90% (≈6 more passing run(s)), then reach 5 clean runs to unlock Autonomous. |
| Tests and live verification, run `zero-footprint-installer-npx-zero-clone-v1-1-0-5` (`test-authoring`) | T2 (≥90%) | ✅ pass · 100% | ✅ pass · 75% | ✅ pass · 100% | ✅ pass · 50% | ✅ pass · 100% | Yes | 1/5 | Guided → **Actionlist** → Autonomous | Raise Action 50% → 90% (≈16 more passing run(s)); Data 75% → 90% (≈6 more passing run(s)), then reach 5 clean runs to unlock Autonomous. |
| Plugin code changes, run `zero-footprint-installer-npx-zero-clone-v1-1-0-2` (`code-implementation`) | T3 (≥95%) | ✅ pass · 75% | ✅ pass · 100% | ✅ pass · 100% | ❌ fail · 75% | ✅ pass · 100% | No — failed: Action | 2/10 | Guided → **Actionlist** → Autonomous | Raise Orchestrator 75% → 95% (≈16 more passing run(s)); Action 75% → 95% (≈16 more passing run(s)), then reach 10 clean runs to unlock Autonomous. |
| Plugin code changes, run `zero-footprint-installer-npx-zero-clone-v1-1-0-6` (`code-implementation`) | T3 (≥95%) | ✅ pass · 75% | ✅ pass · 100% | ✅ pass · 100% | ✅ pass · 75% | ✅ pass · 100% | Yes | 2/10 | Guided → **Actionlist** → Autonomous | Raise Orchestrator 75% → 95% (≈16 more passing run(s)); Action 75% → 95% (≈16 more passing run(s)), then reach 10 clean runs to unlock Autonomous. |

How to read it: the two `--retried` runs (Red's installer work and Blue's wrappers) met acceptance first time but needed a second round after review and smoke found defects, so the scoring rule fails their Action stage. The regression-test run fails Action because the first CI run failed on Python 3.9; runs are append-only, so the later green CI does not rewrite it. Plugin code changes are T3 and need 10 clean runs at 95% plus operator level L6 to run autonomously; the operator is L4, so a human go/no-go stays in place.

## Files created/changed

- **Commits:** `b4ef138`, `89b399e`, `edb7a24`, plus this closing commit, on `release/v1.1.0-zero-footprint-installer` (pull request #1).
- **Added:** `scripts/actionboard_uninstall.py`, `packages/installer/`, `packages/installer-py/`, `.github/workflows/release.yml`, `tests/installer/`, `tests/smoke/results-2026-10-v1.1.md`, this mission directory.
- **Changed:** `scripts/install.py`, `tests/install/test_install.py`, `.github/workflows/ci.yml`, `.gitignore`, `README.md`, `CHANGELOG.md`, `src/VERSION`, `dist/` (three manifests), `.claude-plugin/marketplace.json`, `.actionboard/registry.json`.
