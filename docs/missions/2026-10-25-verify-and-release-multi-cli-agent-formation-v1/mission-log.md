# Mission Log — Verify and release the multi-CLI Agent Formation v1.0.0

Mission: `urn:voltron:mission:verify-and-release-multi-cli-agent-formation-v1` · Started: 2026-10-25

This log records execution as it happens. The Mission Report (`mission-report.md` and
`mission-report.jsonld`) is written only after every assignment has reported `done` or `blocked`.

## Step 0 — Preflight (Black Agent)

| Check | Result | Detail |
|---|---|---|
| Context7 MCP | Ready | Answered `resolve-library-id` and `query-docs` in this session; `claude mcp list` reports `context7: https://mcp.context7.com/mcp (HTTP) - Connected`. |
| Graphify | Graph ready | `graphifyy` upgraded from 0.8.39 to 0.9.95 at the user's request. Built offline with `graphify extract . --code-only` and `graphify cluster-only . --no-label --no-viz`: 551 nodes, 948 edges, 26 communities, token cost 0 input and 0 output. `graphify-out/` is git-ignored. |
| Terse output | Not yet decided | Waiting for the user's answer to the preflight question. Until then, agent chatter is written normally. |

Files created/changed: `graphify-out/` (local, git-ignored).

## Assignment 1 — Environment recon (Green Agent) — done

| CLI | Version | Authenticated | Non-interactive command | Context7 |
|---|---|---|---|---|
| Claude Code | 2.1.310 | Yes | `claude -p` | Connected |
| OpenCode | 2.1.4 (`@opencode/cli`, upgraded during this session from 1.19.4) | Yes (Anthropic API key stored) | `opencode run` | Connected (from the installed `opencode.json`) |
| Antigravity CLI | 1.4.7 | Yes (Gemini models listed) | `agy -p` | Shipped in the plugin's `mcp_config.json`; plugin validates with one MCP server |
| Codex CLI | Not installed | — | `codex exec` | — |

Other findings:

- `openshell` is not on PATH, so no live test can execute a real OpenShell command.
- Node v24.16.0 and `uv` are available; `pipx` is not.
- CI on `main` was green for the previous commit; the cost-and-context commit was still running at the time of recon.
- **OpenCode 2.x changed its plugin API** (no `tool.execute.before`, shell tool renamed to `shell`), so the 1.x guard plugin never fired on the user's OpenCode. This was escalated and fixed in the same session (see below).

Files created/changed: none.

## Out-of-plan fixes found during recon (Black Agent, with the user's standing instruction to proceed)

| Finding | Fix | Live evidence |
|---|---|---|
| OpenCode 2.1.4 ignored the guard plugin | New 2.x plugin on `ctx.permission.hook("evaluate")` with native ask; 1.x plugin kept as legacy and selected by `install.py` | `opencode run`: `permission.rejected: ActionBoard guard: Refusing a cross-workspace sandbox delete…` |
| agy 1.4.7 hook failed on Windows because of re-escaped quotes | Installer writes unquoted paths unless they contain spaces (also applied to Codex `commandWindows`) | `agy -p`: `tool call denied by pre-tool hook: Refusing a cross-workspace sandbox delete…` |

Files created/changed: `adapters/opencode/plugins/actionboard-guard.ts`, `adapters/opencode/actionboard/guard-client.ts`, `adapters/opencode/legacy/actionboard-guard.v1.ts`, `adapters/opencode/adapter.py`, `adapters/antigravity/hooks.json`, `adapters/antigravity/adapter.py`, `adapters/codex/hooks.json`, `adapters/codex/adapter.py`, `scripts/install.py`, `tests/opencode/plugin.test.mjs`, `tests/install/test_install.py`, `docs/capability-matrix.md`, `README.md`, `CHANGELOG.md`, `dist/` (regenerated).

## Scope addition: AI-ops maturity in every mission report (user request)

| Change | Where |
|---|---|
| `maturity.py record` / `summary`, built on `gate_check.py` (same tiers, thresholds, 20-run window, 90-day staleness, clean-run rule) | `src/skills/actionboard-devops-mission/scripts/maturity.py` |
| Mandatory `## Maturity & Progress Summary` section: 5-stage breakdown, Clean Run, tier, clean runs (for example 3/5), Guided → Actionlist → Autonomous, next milestone | `mission-report` skill, DevOps report template, KB format (`MaturityProgress` node) |
| Black Agent scores and records every mission at the end, even when nothing is written to disk | `src/agents/black-agent.md` |
| 17 new tests, including one proving the execution mode always equals `gate_check.py`'s verdict; CI step added | `tests/maturity/test_maturity.py`, `.github/workflows/ci.yml` |
| Mission plan updated: baseline note, smoke and retest checks, Skills Gap row, two new risks | `mission-plan.md`, `mission-plan.jsonld` |

This mission's own Mission Report will be the first to carry the section.

Files created/changed: `src/skills/actionboard-devops-mission/scripts/maturity.py`, `src/skills/actionboard-devops-mission/SKILL.md`, `src/skills/actionboard-devops-mission/assets/mission-report-template.md`, `src/skills/mission-report/SKILL.md`, `src/skills/actionboard-kb/references/mission-knowledge-format.md`, `src/skills/skills-registry/actions-map.json`, `src/agents/black-agent.md`, `tests/maturity/test_maturity.py`, `tests/build/test_build.py`, `.github/workflows/ci.yml`, `.gitignore`, `README.md`, `CHANGELOG.md`, `mission-plan.md`, `mission-plan.jsonld`, this log, `dist/` (regenerated).

## Assignment 2 (Codex bring-up) and Assignment 3 (smoke round 1) — done

The user installed Codex CLI 0.164.0 (standalone, signed in with ChatGPT), approved token spend for
full `/start-mission` runs, chose terse output on and operator level L4, and asked to leave the
Claude Code Graphify skill untouched. A power outage interrupted the first round of runs; they
were restarted from a checked state.

All four CLIs now pass the full mission end to end: preflight, Green recon, the four-part report,
the go/no-go stop, implementation, tests (verified by re-running them independently), registry
writes, and the Maturity & Progress Summary. Six defects were found and fixed along the way; see
`tests/smoke/results-2026-10.md`.

Files created/changed: `tests/smoke/results-2026-10.md`, `src/commands/start-mission.md`,
`src/agents/black-agent.md`, `src/skills/mission-report/SKILL.md`,
`src/skills/mission-preflight/SKILL.md`, `adapters/claude/adapter.py`,
`adapters/claude/hooks/hooks.json`, `adapters/antigravity/adapter.py`,
`adapters/common/hooks/cli_hook.py`, `tests/build/test_build.py`, `tests/guard/test_cli_hook.py`,
`README.md`, `dist/` (regenerated).

## Assignment 4 (release candidate) and Assignment 5 (smoke round 2)

- **Assignment 4:** `src/VERSION` set to 1.0.0 and `dist/` rebuilt; every manifest reads 1.0.0; all
  suites and both CLI validators pass (`53e79c5`).
- **Round 2:** a second mission of the same kind (`GET /version` plus a unit test) ran on all four
  CLIs. Every CLI stopped at the gate, built the endpoint, and passed its tests (re-run by me).
  `code-implementation` reached **2 clean runs** on every CLI. Black Agent re-ran Yellow Agent's
  exact test command on every CLI; the new verification rule works.
- **Two defects found in round 2 and fixed in source:**
  1. Preflight skipped `.graphifyignore` when a graph already existed, so the Antigravity graph
     still held agent tooling (560 nodes). Preflight now always ensures the file first and rebuilds
     the graph when it had to add lines.
  2. Green Agent handed Yellow a `python …` command, but on this Windows machine `python` is a
     Microsoft Store placeholder; Claude Code scored that Data stage as a fail. Green now confirms
     the interpreter starts (`python --version`, `py --version`) and hands over the form that works.
  A build test covers both fixes on all four CLIs. A live re-run of these two fixes is outstanding,
  so assignment 5 stays active.
- **Maturity scoring of this mission:** five assignments were scored into the repository's own
  registry (`.actionboard/registry.json`). `maturity.py` now prints one row per assignment, even when
  two assignments share an action type. The Mission Report is drafted.

Files created/changed: `src/VERSION`, `src/skills/mission-preflight/SKILL.md`,
`src/agents/green-agent.md`, `src/skills/actionboard-devops-mission/scripts/maturity.py`,
`tests/build/test_build.py`, `tests/maturity/test_maturity.py`, `.actionboard/registry.json`,
`mission-report.md`, `mission-report.jsonld`, this log, `tests/smoke/results-2026-10.md`,
`CHANGELOG.md`, `dist/` (regenerated).

## Assignments 6 and 7 — release documentation and deprecation draft

The user chose to skip the live re-run of the two round-2 fixes (build tests cover them) and go
straight to the release documentation.

- **Security defect 9 (Antigravity hook).** Settling the matrix's open item "`allow` vs no output"
  against agy's own hook contract showed that `allow` means "automatically allow the tool
  execution": the hook approved every `run_command` and overrode the user's approval setting.
  Live tests on agy 1.4.7 in scratch projects: an answer without a decision is a deny; `ask`
  defers to the user's setting; `toolPermission: always-proceed` (this machine's setting) approves
  even `force_ask`, so a guard ask (`openshell workspace delete team`) ran. Fix in
  `adapters/common/hooks/cli_hook.py`: no objection → `ask`, guard ask → `force_ask`, guard ask under
  always-proceed → deny. Live after the fix: harmless command ran, workspace delete denied with the
  always-proceed reason, `sandbox delete --all` denied. Two guard tests added (`1156f33`).
- **Claude Code guard verified live:** `openshell sandbox delete --all` through the `PowerShell` tool
  was blocked by the hook.
- **Docs:** README (tested versions, live status, two new known gaps, maturity tests), capability
  matrix (no ⚠️ left; resolved-items table with evidence; one open item: Codex live denial),
  `docs/index.html` (four CLIs, installer panel, `src/` authoring flow, capabilities check verified
  against the repository), CHANGELOG `1.0.0 — 2026-10-25`, PLAN.md Definition of Done (three
  ticked, two linked to what is open).
- **Assignment 7 prepared, not opened:** local branch `docs/point-to-multi-cli-successor` in the
  v0.6.1 checkout (commit `1ed1f07`, README banner only), PR text in `deprecation-pr.md` and
  `deprecation-pr-body.md`. Found while preparing: the v0.6.1 repository is public and
  `ab-mission-command-center` is private, so the banner link would not open for public readers.
- **Scored:** assignment 6 as `code-implementation` run `-6`, not clean: Orchestrator fails because
  the security fix touched files outside the assignment's ownership without a re-plan.

Files created/changed: `adapters/common/hooks/cli_hook.py`, `tests/guard/test_cli_hook.py`,
`dist/` (three hook copies), `README.md`, `docs/capability-matrix.md`, `docs/index.html`,
`CHANGELOG.md`, `PLAN.md`, `tests/smoke/results-2026-10.md`, `.actionboard/registry.json`,
`mission-report.md`, `mission-report.jsonld`, `deprecation-pr.md`, `deprecation-pr-body.md`, this
log; in the v0.6.1 checkout, `README.md` on a local branch.

## Assignment status

| # | Agent | Assignment | Status | Next step |
|---|---|---|---|---|
| 1 | Green | Environment recon | Done | — |
| 2 | Blue | Codex CLI bring-up | Active | The full mission passes on Codex 0.164.0; the guard hook's live denial still needs one interactive `/hooks` trust step. |
| 3 | Yellow | Live smoke round 1 (Claude Code, OpenCode, Antigravity) | Done | All four CLIs pass; six defects fixed. |
| 4 | Red | Fix defects and cut release candidate | Done | RC 1.0.0 (`53e79c5`), CI green. |
| 5 | Yellow | Regression tests, Codex smoke, retest | Active | Trust Codex hooks with `/hooks` and observe a live denial. Round-2 fixes: live re-run skipped by the user. |
| 6 | Red | Release documentation | Done | Docs final; security defect 9 fixed (`1156f33`). |
| 7 | Blue | Deprecation note on the v0.6.1 repository | Prepared | Needs the user's approval and a visibility decision for the new repository; see `deprecation-pr.md`. |
