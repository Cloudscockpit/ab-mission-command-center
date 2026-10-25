# Smoke results — October 2026 (round 1)

Mission: `verify-and-release-multi-cli-agent-formation-v1`, assignment 3 (and the Codex run planned for
assignment 2). Run on 2026-10-25 on Windows 11, Python 3.14.6, Graphify 0.9.95.

**Setup.** Four throwaway Git projects with the same tiny Python JSON service (`app.py` with
`/health`, two unit tests). Each project had `.actionboard/preferences.json` (Graphify enabled,
terse output on) and `.actionboard/config.json` (operator level L4), matching the user's answers.
Objective for every CLI: `add a GET /hello endpoint that returns {"hello": "world"}, with a unit test`.
`openshell` is not installed, so no OpenShell command could execute. Runs used normal permission
modes: no permission-bypass flags.

| CLI | Version | Phase 1 command | Phase 2 command |
|---|---|---|---|
| Claude Code | 2.1.310 | `claude -p --plugin-dir dist/claude --permission-mode acceptEdits --allowedTools <list> "/actionboard-v5-agentformation:start-mission …"` | `claude -p … --resume <session> "go"` |
| OpenCode | 2.1.4 | `opencode run --agent black-agent -m anthropic/claude-sonnet-5-5 "<start-mission text>"` | `opencode run -c --agent black-agent … "go"` |
| Antigravity CLI | 1.4.7 | `agy -p "/start-mission …" --mode accept-edits` | `agy -c -p "go" --mode accept-edits` |
| Codex CLI | 0.164.0 | `codex exec -s workspace-write "$start-mission …"` | `codex exec resume --last "go"` |

## Final results (after fixes)

Every row was checked independently. I re-ran the project's tests myself, called
`app.handle('/hello')`, and read `.actionboard/registry.json`; none of it relies on the agents'
own claims.

| Check | Claude Code | OpenCode | Antigravity | Codex |
|---|---|---|---|---|
| Preflight: Context7 answered | ✅ | ✅ | ✅ | ✅ |
| Preflight: offline code graph built (nodes) | ✅ 18 | ✅ 23 (after `.graphifyignore`) | ✅ 302 | ✅ 305 |
| Preflight: terse output on (preference honoured) | ✅ | ✅ | ✅ | ✅ |
| Green Agent dispatched for recon | ✅ | ✅ | ✅ | ✅ |
| Four-part report (Brief, Assignments, Skills Gap, Risk Register) | ✅ | ✅ | ✅ | ✅ |
| Stopped at the go/no-go gate | ✅ | ✅ | ✅ | ✅ |
| After `go`: `/hello` implemented | ✅ | ✅ | ✅ | ✅ |
| Unit tests pass (`py -m unittest`, run by me) | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 | ✅ 3/3 |
| Runs recorded in `.actionboard/registry.json` | ✅ 2 actions | ✅ 2 actions | ✅ 2 actions | ✅ 3 actions |
| `## Maturity & Progress Summary` in the mission summary | ✅ | ✅ | ✅ | ✅ |
| Mission documents in full prose with terse output on | ✅ | ✅ | ✅ | ✅ |
| `Files created/changed:` lists present | ✅ | ✅ | ✅ | ✅ |

Antigravity and Codex graph sizes include the installed ActionBoard tooling, because those runs
happened before the `.graphifyignore` fix. A re-run will show app-only graphs.

## Defects found and fixed during the round

| # | CLI | Symptom | Root cause | Fix | Verified by |
|---|---|---|---|---|---|
| 1 | Claude Code | Preflight stopped: "Context7 MCP missing" | Agent `tools:` lists named no MCP tools, so Black Agent (as a subagent) could not see Context7 | Every Claude agent lists `mcp__plugin_actionboard-v5-agentformation_context7__*` and `mcp__context7__*`; Antigravity agents set `inheritMcp: true`; build test | Re-run: Context7 answered |
| 2 | Claude Code | Agents reported "no Bash", no graph, no maturity scoring | On this Windows setup Claude Code's shell tool is `PowerShell`; agents listed only `Bash`. The guard hook matched only `Bash` too | Agents list `Bash` and `PowerShell`; hook matcher `Bash\|PowerShell`; guard test for PowerShell | Re-run: graph built, scoring ran |
| 3 | Claude Code | After `go`, Black Agent refused a relayed "go", the main session ran Red/Yellow itself and maturity was never scored | Black Agent ran as a subagent; the user's go reached it only second-hand (it correctly refuses relayed approvals), and nested dispatch is unreliable | `/start-mission` on Claude Code now makes the main session play Black Agent (same as the other CLIs) | Re-run: full mission, registry written, summary present |
| 4 | OpenCode | Phase 1 edited `app.py` without a go/no-go gate | `opencode run "/start-mission …"` does not expand commands in 2.x; the text went to the default `build` agent on the free default model | Documented in README Known gaps: use the TUI, or `--agent black-agent` in scripts | Re-run with `--agent black-agent`: stopped at the gate |
| 5 | OpenCode | Code graph indexed `.opencode/` tooling (318 nodes) instead of the app | Graphify indexes everything not git-ignored | Preflight writes `.graphifyignore` excluding agent tooling folders | 23 nodes, app files only; `graphify update` respects it |
| 6 | All | Yellow Agent's own `test-authoring` work could never pass the Action stage on Claude Code, while the other CLIs passed it anyway | The rubric required verification "by someone other than the Agent that did the work" but named no verifier for Yellow | Rubric: for Yellow's own work, Black Agent re-runs the exact test command from Yellow's report; Black's rules allow exactly that | Consistent rule now ships to all four CLIs (re-run in round 2) |

Earlier in the same session, before this round: the OpenCode 2.x guard plugin rewrite and the
Antigravity Windows hook-quoting fix (see `docs/capability-matrix.md`, Live verification).

## Still open

- Round 2 (assignment 5): repeat the mission on each CLI to confirm clean-run counts rise
  (`1/3` → `2/3`) and that `test-authoring` now passes the Action stage under the new rule.
- Interactive-only checks: the `/` menu entries in each TUI, and Codex's `/hooks` trust prompt.
