# Capability Matrix

Phase 0 research from the CLI docs, then checked live on 2026-10-25 against the versions the
1.0.0 release was tested with: **Claude Code 2.1.310, OpenCode 2.1.4, Codex CLI 0.164.0,
Antigravity CLI (`agy`) 1.4.7** (Windows 11, Python 3.14). Evidence for each row is in
[Live verification](#live-verification-2026-10-25) and `tests/smoke/results-2026-10.md`.

✅ supported · ❌ not supported · — not used by this package

| Capability | Claude Code | OpenCode | Codex CLI | Antigravity CLI |
|---|---|---|---|---|
| Skills (`SKILL.md`) | ✅ plugin `skills/` | ✅ `.opencode/skills`, `.agents/skills`, `.claude/skills` | ✅ `.agents/skills`, `~/.agents/skills` | ✅ `.agents/skills`, plugin `skills/` |
| Custom agents / subagents | ✅ `agents/*.md` | ✅ `.opencode/agents/*.md` | ✅ `.codex/agents/*.toml` | ✅ `.agents/agents/*.md`, plugin `agents/` |
| Dispatch tool | `Agent` | `task` | `spawn_agent` + `wait_agent` | `invoke_subagent` |
| Nested delegation (subagent → subagent) | ❌ in practice (smoke round 1, defect 3) → session plays Black | ❌ by default (`subagent_depth` = 1) | ❌ by default (`agents.max_depth` = 1) | ✅ up to 10 levels (not needed) |
| Slash commands with args | ✅ `commands/*.md`, `$ARGUMENTS` | ✅ `.opencode/commands/*.md`, `$ARGUMENTS` (TUI only: `opencode run` does not expand them on 2.x) | ❌ prompts are deprecated and user-level only → **skill** `$start-mission` | ❌ workflows are deprecated → **skill** `/start-mission` |
| Pre-tool hook: block | ✅ live | ✅ 2.x `ctx.permission.hook("evaluate")`, live; 1.x `tool.execute.before` + throw | ✅ `PreToolUse` (payload and Windows command unit-tested; live denial needs the one-time `/hooks` trust, see [Open item](#open-item)) | ✅ `PreToolUse`, live |
| Pre-tool hook: ask | ✅ | ✅ 2.x native; ❌ 1.x → static ask patterns | ❌ (parsed, unsupported) → `.rules` `prompt` | ✅ `force_ask`; ❌ under `toolPermission: always-proceed`, which approves it → denied instead (live) |
| Post-tool hook (audit) | ✅ | ✅ `execute.after` (2.x), `tool.execute.after` (1.x) | ✅ `PostToolUse` | ✅ `PostToolUse` |
| Shell tool name | `Bash`, or `PowerShell` on Windows | `shell` (2.x), `bash` (1.x) | `Bash`, `shell`, `exec_command`, `local_shell` | `run_command` |
| Per-agent model | ✅ `opus`/`sonnet`/`inherit` | ✅ `provider/model` | ✅ `model` in agent TOML | ✅ tier only: `inherit`/`flash`/`pro` |
| Per-agent tool restriction | ✅ `tools` | ✅ `permission` | ❌ (only `features.shell_tool = false`; sandbox is inherited) | ✅ `tools` |
| MCP (Context7) | ✅ plugin `.mcp.json`; agents list the MCP tools | ✅ `opencode.json` `mcp` | ✅ `.codex/config.toml` `[mcp_servers]` | ✅ plugin `mcp_config.json`; agents set `inheritMcp` |
| Plugin / package format | ✅ `.claude-plugin/plugin.json` + marketplace | — (files copied into `.opencode/`) | — (files installed into `.agents/` and `.codex/`; Codex plugins cannot carry agents) | ✅ `plugin.json` (`agy plugin validate --strict`) |
| Project context file | `CLAUDE.md` | `AGENTS.md` | `AGENTS.md` | `AGENTS.md` / `GEMINI.md`, plugin `rules/AGENTS.md` |

## How the gaps are handled

| Gap | Fallback used |
|---|---|
| No nested delegation (Claude in practice, OpenCode, Codex) | Black Agent is the **session itself** on every CLI: Claude Code's `/start-mission` has the main session read Black Agent's manual; OpenCode runs `/start-mission` as `agent: black-agent` (`mode: primary`); Codex and Antigravity run the `start-mission` skill, which bundles Black Agent's prompt as `references/black-agent.md`. The specialists are one level deep. |
| No custom commands (Codex, Antigravity) | `/start-mission` ships as a skill of the same name. |
| No hook "ask" (OpenCode 1.x, Codex; Antigravity under `always-proceed`) | The guard reports which rule fired and whether the command is one plain `openshell ...` call. A plain call whose rule the CLI's static rules can express is let through so the static rule prompts; anything else is **denied** with the reason. OpenCode 1.x: `permission.bash` ask patterns in every agent. Codex: `.codex/rules/actionboard.rules` (`prompt` / `forbidden`). Antigravity under `toolPermission: always-proceed`: every guard ask is denied. OpenCode 2.x, Claude Code, and Antigravity otherwise ask natively. |
| No per-agent tool restriction (Codex) | Read-only roles (Green, Yellow's "no production code") are enforced by instructions only. Documented as a known gap. |
| No sequential-role fallback needed | Every target has subagents, so the plan's "sequential role mode" is not used. |

## Resolved items

Each item the Phase 0 research could not settle, and how it was settled.

| Item | Result | Evidence |
|---|---|---|
| Claude Code nested delegation | ❌ in practice: a subagent Black refused the relayed "go" and its dispatch was unreliable | Smoke round 1, defect 3; `/start-mission` now makes the session play Black |
| Codex agent names with hyphens (`red-agent`) | ✅ work as written | Smoke round 1: `spawn_agent` with `green-agent`, `red-agent`, `yellow-agent` |
| Codex plugin hooks in the CLI | — not used | The adapter installs `.codex/hooks.json` instead |
| Codex hook command quoting on Windows | ✅ | Installer writes unquoted paths without spaces (same fix agy needed); `tests/install` |
| Antigravity `{"decision": "allow"}` vs no output | ❌ both wrong. `allow` auto-approves the call and skips the user's approval setting (security defect 9, fixed); an object without a decision is a **deny**. The hook now answers `ask` (defers to the user's setting) when it has no objection and `force_ask` for a guard ask | Live on agy 1.4.7, 2026-10-25; `tests/guard/test_cli_hook.py::test_antigravity_never_sends_allow` |
| Antigravity `force_ask` under `toolPermission: always-proceed` | ❌ approved without a prompt → the hook denies guard asks under that setting | Live on agy 1.4.7; `test_antigravity_always_proceed_turns_asks_into_denies` |

### Open item

| Item | Why open | What closes it |
|---|---|---|
| Codex: a live guard denial | Codex runs project hooks only after they are trusted once in the interactive `/hooks` screen, which a scripted run cannot do | In a Codex window on a project with the formation installed: `/hooks`, trust, then ask it to run `openshell sandbox delete --all`. Expected: denied with "Refusing a cross-workspace sandbox delete…" |

## Live verification (2026-10-25)

Real CLI runs in throwaway projects, with `openshell` absent from PATH so nothing could execute.

| CLI | Version | Result |
|---|---|---|
| OpenCode | **2.1.4** (`@opencode/cli`) | Six agents load with the right modes; v1-style `permission` rules are translated to 2.x `shell` rules; Context7 shows `connected`. **2.x dropped `tool.execute.before`** and renamed the shell tool to `shell`, so the 1.x plugin never fired. Replaced by a 2.x plugin (`default { id, setup }`, `ctx.permission.hook("evaluate")`, native **ask**). Live run: `openshell sandbox delete --all-workspaces` → `permission.rejected: ActionBoard guard: Refusing a cross-workspace sandbox delete…`. The 1.x plugin ships as `actionboard/legacy/` and `install.py` picks it when it detects OpenCode 1.x. |
| Antigravity CLI | **1.4.7** | Workspace plugin loads and its PreToolUse hook runs. **Bug found and fixed:** agy re-escapes quotes as `\"` before `cmd /c`, so a quoted Python path failed; when the hook failed, agy blocked the tool (fail-closed, previously unverified). After the fix, live run → `tool call denied by pre-tool hook: Refusing a cross-workspace sandbox delete…`. |
| Claude Code | 2.1.310 | Full mission passes (smoke 4.3). Fixed on the way: agents now list the Context7 MCP tools and `PowerShell` (the Windows shell tool), and `/start-mission` makes the main session play Black Agent, because a subagent Black refused the relayed "go" and nested dispatch was unreliable. **Nested delegation: ❌ in practice → session-plays-Black, as on every CLI.** Guard, live: `openshell sandbox delete --all` through the `PowerShell` tool → `PreToolUse:PowerShell hook error: Refusing a cross-workspace sandbox delete…`. |
| Codex CLI | 0.164.0 | Full mission passes (smoke 6.6): `$start-mission`, `spawn_agent` with `green-agent` / `red-agent` / `yellow-agent` (hyphenated names work), Context7 from `config.toml`, offline graph, maturity summary. |
| Antigravity CLI (again) | 1.4.7 | **Security defect 9 found and fixed:** the hook's no-objection answer was `allow`, which auto-approves. Live after the fix, with the user's `toolPermission: always-proceed`: a harmless command ran, `openshell workspace delete team` was denied ("…Antigravity is set to always-proceed…"), `openshell sandbox delete --all` was denied. |

Full results of both rounds and the defects fixed: `tests/smoke/results-2026-10.md`.

## Guard limits

The guard is defense in depth, not a sandbox. A security review on 2026-10-25 found 16
bypasses in the parser (most inherited from v0.6.1); all are fixed and pinned by
`tests/guard/test_guard.py::test_review_bypasses_are_closed`. Fixes: quote-aware splitting on
`&`, `|&` too; the most severe finding across all calls wins; the subcommand is found past
global flags; `$`/backtick expansion inside an openshell call asks; `-lc`/`cmd /c` payloads
are unwrapped; nesting past three shells asks; any bare `openshell` word the parser cannot
attribute to an invocation asks (pipes into `sh`, `python -c`, `iex`, unknown wrappers,
Windows paths); encoded PowerShell asks; crashes and undecodable input fail closed.

What remains out of reach, by design:

- Text assembled at runtime with no literal `openshell` (`a=open; b=shell; $a$b …`).
- Scripts written in one call and run in a later call that never names `openshell`.
- On Codex, hosted tools that skip hooks.
- On Antigravity, a run started with `--mode auto` or `--dangerously-skip-permissions` may
  approve guard asks; the hook cannot see those flags (it does see `toolPermission`).
  Guard denies still block.
- The audit log sits in the agent's working tree, so it is advisory, not tamper-evident;
  set `OPENSHELL_AUDIT_LOG` to a path outside the workspace when that matters.

Run agents inside an OpenShell sandbox (`sandbox-up`, `mission-harness`) when the guard
alone is not enough.

## Sources

- Claude Code: plugin reference (`claude plugin validate` passes for `dist/claude` and the root marketplace).
- OpenCode: <https://opencode.ai/docs/agents/>, <https://opencode.ai/docs/commands/>, <https://opencode.ai/docs/skills/>, <https://opencode.ai/docs/plugins/>, <https://opencode.ai/docs/rules/>; `packages/plugin/src/index.ts` @ v1.19.4; `opencode agent list` loads all six agents.
- Codex: <https://learn.chatgpt.com/docs/build-skills>, <https://learn.chatgpt.com/docs/agent-configuration/subagents>, <https://learn.chatgpt.com/docs/hooks>, <https://learn.chatgpt.com/docs/agent-configuration/rules>, <https://learn.chatgpt.com/docs/agent-configuration/agents-md>, <https://developers.openai.com/codex/plugins/build>.
- Antigravity: docs bundled with agy 1.4.0 (`~/.gemini/antigravity-cli/builtin/skills/agy-customizations/`), <https://antigravity.google/docs/subagents>, <https://antigravity.google/docs/hooks>, <https://antigravity.google/docs/plugins>, `agy plugin validate`; hook decisions (`allow`, `deny`, `ask`, `force_ask`) from `docs/hooks.md` bundled with agy 1.4.7.
