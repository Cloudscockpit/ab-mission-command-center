# Capability Matrix

Phase 0 research, checked 2026-10-25 against Claude Code, OpenCode 1.19.4, Codex CLI (docs
only, not installed), and Antigravity CLI `agy` 1.4.0.

✅ supported · ❌ not supported · ⚠️ supported but unverified at runtime (see notes)

| Capability | Claude Code | OpenCode | Codex CLI | Antigravity CLI |
|---|---|---|---|---|
| Skills (`SKILL.md`) | ✅ plugin `skills/` | ✅ `.opencode/skills`, `.agents/skills`, `.claude/skills` | ✅ `.agents/skills`, `~/.agents/skills` | ✅ `.agents/skills`, plugin `skills/` |
| Custom agents / subagents | ✅ `agents/*.md` | ✅ `.opencode/agents/*.md` | ✅ `.codex/agents/*.toml` | ✅ `.agents/agents/*.md`, plugin `agents/` |
| Dispatch tool | `Agent` | `task` | `spawn_agent` + `wait_agent` | `invoke_subagent` |
| Nested delegation (subagent → subagent) | ⚠️ v0.6.1 relies on it (Black runs as a subagent and dispatches Green); Claude Code docs have said subagents cannot spawn subagents — verify in smoke test 4.3 | ❌ by default (`subagent_depth` = 1) | ❌ by default (`agents.max_depth` = 1) | ✅ up to 10 levels |
| Slash commands with args | ✅ `commands/*.md`, `$ARGUMENTS` | ✅ `.opencode/commands/*.md`, `$ARGUMENTS` | ❌ prompts are deprecated and user-level only → **skill** `$start-mission` | ❌ workflows are deprecated → **skill** `/start-mission` |
| Pre-tool hook: block | ✅ | ✅ `tool.execute.before` + throw | ✅ `PreToolUse` | ✅ `PreToolUse` |
| Pre-tool hook: ask | ✅ | ✅ 2.x `ctx.permission.hook("evaluate")`; ❌ 1.x → static ask patterns | ❌ (parsed, unsupported) → `.rules` `prompt` | ✅ |
| Post-tool hook (audit) | ✅ | ✅ `tool.execute.after` | ✅ `PostToolUse` | ✅ `PostToolUse` |
| Shell tool name | `Bash` | `bash` | `Bash` | `run_command` |
| Per-agent model | ✅ `opus`/`sonnet`/`inherit` | ✅ `provider/model` | ✅ `model` in agent TOML | ⚠️ tier only: `inherit`/`flash`/`pro` |
| Per-agent tool restriction | ✅ `tools` | ✅ `permission` | ❌ (only `features.shell_tool = false`; sandbox is inherited) | ✅ `tools` |
| Plugin / package format | ✅ `.claude-plugin/plugin.json` + marketplace | — (files copied into `.opencode/`) | ⚠️ `plugin.json`; agents are not plugin components | ✅ `plugin.json` (`agy plugin validate`) |
| Project context file | `CLAUDE.md` | `AGENTS.md` | `AGENTS.md` | `AGENTS.md` / `GEMINI.md`, plugin `rules/AGENTS.md` |

## How the gaps are handled

| Gap | Fallback used |
|---|---|
| No nested delegation (OpenCode, Codex; possibly Claude) | Black Agent is the **session itself**: OpenCode runs `/start-mission` as `agent: black-agent` (`mode: primary`); Codex and Antigravity run the `start-mission` skill, which bundles Black Agent's prompt as `references/black-agent.md`. The specialists are one level deep. Claude keeps v0.6.1 behaviour for parity; if the smoke test shows Black cannot dispatch from a subagent, switch the Claude command to the same session-plays-Black branch (`<!-- not:claude -->` in `src/commands/start-mission.md`). |
| No custom commands (Codex, Antigravity) | `/start-mission` ships as a skill of the same name. |
| No hook "ask" (OpenCode, Codex) | The guard reports which rule fired and whether the command is one plain `openshell ...` call. A plain call whose rule the CLI's static rules can express is let through so the static rule prompts; anything else is **denied** with the reason. OpenCode: `permission.bash` ask patterns in every agent. Codex: `.codex/rules/actionboard.rules` (`prompt` / `forbidden`). |
| No per-agent tool restriction (Codex) | Read-only roles (Green, Yellow's "no production code") are enforced by instructions only. Documented as a known gap. |
| No sequential-role fallback needed | Every target has subagents, so the plan's "sequential role mode" is not used. |

## Unverified items

| Item | Why unverified | Risk if wrong |
|---|---|---|
| Codex hooks on Windows (`commandWindows`, quoting) | Codex is not installed here | Guard not enforced on Codex/Windows |
| Codex agent names with hyphens (`red-agent`) | Docs examples use underscores | Black Agent has to spawn by a different name |
| Codex plugin hooks in the CLI | Docs only cover the desktop app | The adapter does not use plugin hooks; it installs `.codex/hooks.json` |
| Antigravity `{"decision": "allow"}` vs no output | Docs list both `allow` and `auto_approve` | Treated as "no objection"; `auto_approve` is never sent |
| Codex hook command quoting on Windows | Same risk agy had (see below) | Installer now writes unquoted paths when they contain no spaces |

## Live verification (2026-10-25)

Real CLI runs in throwaway projects, with `openshell` absent from PATH so nothing could execute.

| CLI | Version | Result |
|---|---|---|
| OpenCode | **2.1.4** (`@opencode/cli`) | Six agents load with the right modes; v1-style `permission` rules are translated to 2.x `shell` rules; Context7 shows `connected`. **2.x dropped `tool.execute.before`** and renamed the shell tool to `shell`, so the 1.x plugin never fired. Replaced by a 2.x plugin (`default { id, setup }`, `ctx.permission.hook("evaluate")`, native **ask**). Live run: `openshell sandbox delete --all-workspaces` → `permission.rejected: ActionBoard guard: Refusing a cross-workspace sandbox delete…`. The 1.x plugin ships as `actionboard/legacy/` and `install.py` picks it when it detects OpenCode 1.x. |
| Antigravity CLI | **1.4.7** | Workspace plugin loads and its PreToolUse hook runs. **Bug found and fixed:** agy re-escapes quotes as `\"` before `cmd /c`, so a quoted Python path failed; when the hook failed, agy blocked the tool (fail-closed, previously unverified). After the fix, live run → `tool call denied by pre-tool hook: Refusing a cross-workspace sandbox delete…`. |
| Claude Code | 2.1.310 | `claude plugin validate` passes for the plugin and marketplace; Context7 connected. Live mission run pending (smoke 4.3). |
| Codex CLI | not installed | Pending (assignment 2). |

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
- The audit log sits in the agent's working tree, so it is advisory, not tamper-evident;
  set `OPENSHELL_AUDIT_LOG` to a path outside the workspace when that matters.

Run agents inside an OpenShell sandbox (`sandbox-up`, `mission-harness`) when the guard
alone is not enough.

## Sources

- Claude Code: plugin reference (`claude plugin validate` passes for `dist/claude` and the root marketplace).
- OpenCode: <https://opencode.ai/docs/agents/>, <https://opencode.ai/docs/commands/>, <https://opencode.ai/docs/skills/>, <https://opencode.ai/docs/plugins/>, <https://opencode.ai/docs/rules/>; `packages/plugin/src/index.ts` @ v1.19.4; `opencode agent list` loads all six agents.
- Codex: <https://learn.chatgpt.com/docs/build-skills>, <https://learn.chatgpt.com/docs/agent-configuration/subagents>, <https://learn.chatgpt.com/docs/hooks>, <https://learn.chatgpt.com/docs/agent-configuration/rules>, <https://learn.chatgpt.com/docs/agent-configuration/agents-md>, <https://developers.openai.com/codex/plugins/build>.
- Antigravity: docs bundled with agy 1.4.0 (`~/.gemini/antigravity-cli/builtin/skills/agy-customizations/`), <https://antigravity.google/docs/subagents>, <https://antigravity.google/docs/hooks>, <https://antigravity.google/docs/plugins>, `agy plugin validate`.
