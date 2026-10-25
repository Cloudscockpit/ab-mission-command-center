# Mission Plan — Verify and release the multi-CLI Agent Formation v1.0.0

Mission: `urn:voltron:mission:verify-and-release-multi-cli-agent-formation-v1` · Date: 2026-10-25 · Status: awaiting go/no-go

> No mission-brief document exists for this mission; the slug was derived from the objective here. Reuse it for the brief and the report.

> **Baseline already in the repository at plan time** (not an assignment): the cost and context layer. Mandatory Context7 MCP for all four CLIs, the `mission-preflight` skill (Step 0: Context7 check, Graphify install only after the user agrees, offline code graph, terse output only after the user agrees), the `terse-output` skill derived from Caveman v4.0.1 (Apache-2.0), and the operating policy in every agent (graph-first recon, Context7 version checks, full prose for mission documents, code, commits and security reviews, and a Files created/changed list in every report). This mission verifies it live.

**Step 0 — Preflight** runs before assignment 1: Black Agent loads `mission-preflight`.

## Agent Assignments

| # | Agent | Task | Files Owned | Depends On | Acceptance |
|---|---|---|---|---|---|
| 1 | Green Agent | **Environment recon** — Inventory every CLI on this machine (claude, opencode, agy, codex) with version, auth state and its non-interactive mode (claude -p, opencode run, agy -p, codex exec); confirm openshell is NOT on PATH; confirm the Context7 MCP connects in each CLI (claude mcp list, opencode mcp list, codex mcp list, agy plugin list); recon from ./graphify-out/ built by Black's Step 0 preflight; record the latest CI run on main and which PLAN.md items are still open. | — (read-only) | — | Recon report (standard Green header, Recon mode: graph-backed) with a table CLI \| version \| authenticated \| print-mode command \| Context7 connected, an openshell-absent check, the CI run id + status, the open PLAN.md item list, and a Files created/changed list (none). |
| 2 | Blue Agent | **Codex CLI bring-up and adapter verification** — Install Codex CLI (user runs `codex login`), install dist/codex into a scratch repo, trust hooks via /hooks, and resolve the four UNVERIFIED items in docs/capability-matrix.md: hyphenated agent names, commandWindows quoting on Windows, exec_command payload shape, plugin-vs-project hooks. Patch the Codex adapter only; build to a temp dir with --out to test. | `adapters/codex/adapter.py`<br>`adapters/codex/hooks.json`<br>`adapters/codex/actionboard.rules` | `assignment:1` | In a scratch repo: `codex exec` spawns green-agent by name; the hook denies `openshell sandbox delete --all` (stub openshell) and `openshell workspace delete x` prompts via rules. `codex mcp list` shows context7 from the installed config.toml block. Each UNVERIFIED item is reported as confirmed or changed, with the codex version. |
| 3 | Yellow Agent | **Live smoke round 1 (Claude Code, OpenCode, Antigravity)** — Run smoke tests 4.3, 4.4 (parity vs v0.6.1), 5.8 and 7.6 from tests/smoke/README.md in throwaway repos with the stub openshell first on PATH. Objective: add a /hello endpoint. Check the four-part report, the go/no-go stop, Green running as a separate agent, the / menu entries (/mission-brief, /mission-plan, ...), guard deny/ask behaviour, and the cost layer: preflight asks both opt-in questions with their notes and records .actionboard/preferences.json, Context7 answers, Green recon is graph-backed, and with terse output on the brief/plan/report stay in full prose and every Agent report ends with Files created/changed. Record failures; do not fix them. | `tests/smoke/results-2026-10.md`<br>`tests/smoke/stub/openshell` | `assignment:1` | results-2026-10.md has one row per smoke ID: CLI + version, pass/fail per step, transcript excerpt for every failure. The Claude nested-dispatch question (Black as subagent dispatching Green) is answered yes/no. |
| 4 | Red Agent | **Fix defects and cut release candidate** — Fix every failure from the smoke round and any shared-code change Codex needs; if Claude cannot nest dispatch, switch the Claude start-mission branch to session-plays-Black. Bump src/VERSION to 1.0.0 as the last step and regenerate dist/ and the root marketplace. | `src/`<br>`adapters/claude/`<br>`adapters/opencode/`<br>`adapters/antigravity/`<br>`adapters/common/`<br>`scripts/`<br>`dist/`<br>`.claude-plugin/marketplace.json` | `assignment:2`, `assignment:3` | `py scripts/build.py --check` prints 'dist/ is up to date'; every failing row in results-2026-10.md links a commit; GitHub CI on the pushed branch is green on all jobs; plugin.json versions read 1.0.0. |
| 5 | Yellow Agent | **Regression tests, Codex smoke and retest** — Add a failing-before/passing-after test for every defect fixed in the previous assignment; add the new test directory to CI; run smoke 6.6 (Codex) and re-run every failed row on the release candidate; security re-review any change under src/hooks/ or adapters/*/hooks. | `tests/regressions/test_live_findings.py`<br>`tests/smoke/results-retest-2026-10.md`<br>`.github/workflows/ci.yml` | `assignment:4` | All four CLIs show pass for every smoke step in results-retest-2026-10.md; each fixed defect has a named test; CI green on Windows, macOS, Linux; guard review lists zero open High findings. |
| 6 | Red Agent | **Release documentation** — Update README (tested CLI versions, install per CLI, known gaps), flip capability-matrix ⚠️ rows to ✅/❌ with evidence, port docs/index.html to multi-CLI, write the 1.0.0 CHANGELOG entry, tick PLAN.md Definition of Done. | `README.md`<br>`docs/capability-matrix.md`<br>`docs/index.html`<br>`CHANGELOG.md`<br>`PLAN.md` | `assignment:5` | docs/capability-matrix.md contains no ⚠️; README lists the exact CLI versions from the retest file; CHANGELOG has a dated 1.0.0 section; every PLAN.md DoD box is ticked or has a linked reason. |
| 7 | Blue Agent | **Deprecation note on the v0.6.1 repo** — Open (do not merge) a PR on Cloudscockpit/actionboard-build-mission-pipeline adding a README banner that points to Cloudscockpit/ab-mission-command-center. Outward-facing: needs explicit user approval before the PR is created. | `actionboard-build-mission-pipeline/README.md` | `assignment:6` | A PR URL on the old repo whose diff touches only README.md and links the new repo; it stays open for the user to merge. |

Dispatch order (from Depends On): **1** → **2** ∥ **3** → **4** → **5** → **6** → **7**.

## Skills Gap

| Capability | Status | Notes |
|---|---|---|
| Mandatory Context7 MCP (current library, MCP, plugin, CLI versions) | `covered` | version-lookup -> green-agent; configured for all four CLIs by install.py; verified connected in OpenCode 1.19.4 |
| Code-graph recon with Graphify | `use-existing-skill:mission-preflight` | Asks before installing graphifyy 0.9.95; builds ./graphify-out/ offline with no API key; graphify benchmark measured 11-25x fewer tokens per recon question on this repository |
| Output-token reduction for agent chatter | `use-existing-skill:terse-output` | Conditional: only after the user says yes in preflight; mission documents, code, commits and security reviews stay full prose |
| Environment and codebase recon | `covered` | codebase-recon -> green-agent, graph-backed after Step 0 |
| Scripted CLI smoke runs (claude -p, opencode run, agy -p, codex exec) | `covered` | test-authoring -> yellow-agent via Bash; costs model tokens; needs each CLI authenticated |
| Codex CLI install and auth | `covered` | api-integration -> blue-agent; precondition NOT yet met: user must run `codex login` |
| Visual TUI checks (/ menu, Codex /hooks trust) | `needs-new-skill` | No automation for interactive TUIs; proposed: tui-checklist skill that walks the user through manual checks and records answers. Until then the user does these steps |
| Adapter and core fixes | `covered` | code-implementation -> red-agent |
| Regression tests and CI wiring | `covered` | test-authoring -> yellow-agent |
| Guard security re-review | `covered` | security-review -> yellow-agent |
| Multi-CLI docs site port (docs/index.html) | `covered` | file-scaffolding -> red-agent |
| Cross-repo PR, tag and GitHub release | `needs-new-skill` | No registry action; proposed: release-publish skill (gh pr create, tag, release notes). Tag + release stay a user step after the report |
| Mission report with JSON-LD | `use-existing-skill:mission-report` | mission-report-authoring; requires this plan to exist (met once written) |

## Risk Register

| Category | Risk | Sev | Mitigation |
|---|---|---|---|
| data-loss | A guard regression lets a smoke test run a real destructive openshell command | H | openshell is not installed here; smoke runs put a stub openshell (echo only) first on PATH and assert it was never reached for denied commands |
| scope | Terse output leaks into mission briefs, plans, reports, code, commits or security reviews | H | Full-prose rule in the three document skills, in every agent's operating policy and in terse-output itself; build tests assert the rule ships to every CLI; smoke round checks the documents with terse output on |
| integration | Hosted Context7 server is rate limited or unreachable, and preflight stops every mission | M | Preflight states the failure and the fix in full sentences; optional CONTEXT7_API_KEY raises limits; a user-configured context7 server (local or keyed) is detected and left untouched |
| data-loss | Installing Graphify changes the user's Python environment | L | Asked first with an explanatory note; isolated installers preferred (uv tool, then pipx); version pinned; graphify install/hook commands that edit global CLI config are never run |
| technical | Claude Code subagents cannot dispatch subagents, so Black-as-subagent never runs Green | H | Smoke 4.3 answers it first; fallback is the session-plays-Black branch already used on the other CLIs |
| integration | Codex assumptions are wrong (hyphenated names, Windows hook quoting, exec_command payload) | H | Blue verifies each item live before Red cuts the RC; x-codex name overrides and commandWindows tweaks are adapter-only changes |
| integration | Antigravity workspace plugin loads but the hook 'allow' result auto-approves commands | M | Smoke 7.6 checks a harmless command still prompts per normal agy permissions; if not, emit {} instead of allow |
| technical | Model nondeterminism makes smoke results flaky | M | Fixed objective, throwaway repo, record CLI + model version; a step fails only if it fails twice |
| integration | Private repo blocks marketplace / agy installs from GitHub on other machines | M | Smoke from the local clone; flipping to public is a user decision at release |
| scope | Optional work creeps in (npx/uvx package, default non-Anthropic model maps, new CLIs) | M | Out of scope for this mission; logged as follow-ups in the report |
| data-loss | Installer or smoke runs edit a real project's AGENTS.md or .codex/hooks.json | L | Throwaway repos only; installer refuses foreign files and uninstall is manifest-tracked |
| technical | CLI updates change formats between test and release | L | Pin tested versions in README; golden/dist drift check in CI catches build-side drift |

Mission ready. Reply **go** to dispatch Agents, **no-go** to revise, or **edit <section>**.
