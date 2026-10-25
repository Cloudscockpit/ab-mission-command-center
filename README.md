# ActionBoard V5 Agent Formation (multi-CLI)

Turn one objective into a reviewed plan, then execute it with specialist agents that never
touch the same file. **Nothing runs until you approve.**

Same mission flow on every supported CLI:

1. Black Agent drafts the **Mission Brief**
2. Green Agent runs read-only **recon**
3. Black Agent drafts **Agent Assignments** with file ownership
4. **Skills Gap** analysis
5. **Risk Register**
6. **Go/no-go gate** → you reply `go` → Red/Blue/Yellow execute
7. **Mission Report** (Markdown + schema.org JSON-LD)

| CLI | Tested version | Start a mission | Status |
|---|---|---|---|
| Claude Code | 2.1.310 | `/start-mission <objective>` | Supported; full mission passes live |
| OpenCode | 2.1.4 (1.x via a legacy guard plugin) | `/start-mission <objective>` in the TUI | Supported; full mission passes live |
| Codex CLI | 0.164.0 | `$start-mission <objective>` | Supported; full mission passes live (guard hook needs one-time `/hooks` trust) |
| Antigravity CLI (`agy`) | 1.4.7 | `/start-mission <objective>` | Supported; full mission passes live, `agy plugin validate --strict` passes |

Every CLI ran two full missions live (October 2026): preflight, Green recon, four-part plan, stop at
the go/no-go gate, build, tests re-run independently, maturity scoring. Results:
[`tests/smoke/results-2026-10.md`](tests/smoke/results-2026-10.md).

### Slash commands

Besides `/start-mission`, each user-facing skill is a command of its own:
`/mission-brief`, `/mission-plan`, `/mission-report`, `/skills-registry`,
`/actionboard-devops-mission`, `/mission-harness`, `/sandbox-up`, `/sandbox-status`,
`/sandbox-down`, `/policy-widen` (and `/browser-actions` on Claude Code).

| CLI | How they appear |
|---|---|
| Claude Code | Skills are listed in the `/` menu natively. |
| OpenCode | OpenCode does not list skills in `/`, so the build generates one thin command per skill in `.opencode/commands/` that loads it. |
| Antigravity CLI | Every skill is a `/command` natively (internal ones such as `/openshell-admin` show too). |
| Codex CLI | Skills are invoked as `$mission-brief`, … or picked from `/skills`. |

## Install

Requires **Python 3.9+** (hooks and installer use the standard library only).

```sh
git clone https://github.com/Cloudscockpit/ab-mission-command-center
cd ab-mission-command-center
python scripts/install.py                       # detects CLIs on PATH, asks which, installs into ./
python scripts/install.py --target opencode --project ../my-app
python scripts/install.py --target codex --global
python scripts/install.py --target antigravity --project ../my-app --uninstall
```

The installer records every file it creates and `--uninstall` removes only those (and only
if unchanged). It refuses to overwrite files it did not create unless `--force`.

| CLI | `--project <dir>` installs to | `--global` installs to |
|---|---|---|
| Claude Code | — use the plugin marketplace (below) | — |
| OpenCode | `<dir>/.opencode/` | `~/.config/opencode/` |
| Codex CLI | `<dir>/.agents/skills/`, `<dir>/.codex/{agents,rules,hooks.json}`, block in `<dir>/AGENTS.md` | `~/.agents/skills/`, `~/.codex/…`, `~/.codex/AGENTS.md` |
| Antigravity CLI | `<dir>/.agents/plugins/actionboard-v5-agentformation/` | `~/.gemini/config/plugins/actionboard-v5-agentformation/` |

**Claude Code** — in Claude Code:

```
/plugin marketplace add Cloudscockpit/ab-mission-command-center
/plugin install actionboard-v5-agentformation@actionboard-v5-agentformation
```

The marketplace at `.claude-plugin/marketplace.json` points at `./dist/claude`.

**Codex** — hooks must be trusted once with `/hooks` (Codex re-asks when they change). Until
then the OpenShell guard does not run on Codex.

**Antigravity** — if your agy `toolPermission` is `always-proceed`, agy approves every prompt,
so the guard turns its "ask" rules into denies (see Known gaps).

### Choosing models

By default Claude uses `opus` for Black and `sonnet` for the specialists, Antigravity uses
`pro`/`flash`, and OpenCode and Codex inherit the session model. Override per CLI with a
config file (see `agentformation.config.example.json`):

```sh
python scripts/install.py --target opencode --config agentformation.config.json
```

## The Agents

| Agent | Role | Writes |
|---|---|---|
| **Black** | Mission commander. Plans, delegates, gates, reports. | mission documents only |
| **Green** | Recon — codebase analysis, graphify-aware | nothing |
| **Red** | Rapid execution — builds features | its owned files |
| **Blue** | Data & integrations — APIs, schemas, plumbing | its owned files |
| **Yellow** | Quality & defense — tests, security review | its owned test files |
| `sandbox-warden` | OpenShell sandbox lifecycle | nothing |

## OpenShell guard

Every CLI with hooks runs the same Python guard on shell commands that reach `openshell`.
It parses commands into argv (quotes, `--flag=value`, `bash -c`, `VAR=x` prefixes, operator
chains), and **fails closed** when it cannot.

| Command | Decision |
|---|---|
| `openshell sandbox delete --all` / `--all-workspaces` | deny |
| `openshell sandbox create --env GITHUB_TOKEN=…` (credential-shaped) | deny |
| `openshell policy set --global …` | ask |
| `openshell workspace delete …` | ask |
| `--add-endpoint host:port:full` | ask |
| `$(openshell …)`, backticks, `eval`, `xargs`, subshells | ask |
| unparseable command mentioning openshell | ask |
| `openshell` reached any way the parser cannot follow (pipe into `sh`, `python -c`, unknown wrapper) | ask |

The guard is defense in depth, not a sandbox; see the limits in
[`docs/capability-matrix.md`](docs/capability-matrix.md#guard-limits).

State-changing `openshell` calls are appended to `.openshell-audit.log` (or
`$OPENSHELL_AUDIT_LOG`).

## Cost optimisation and up-to-date context

Every mission starts with **Step 0 — preflight** (`mission-preflight` skill, also `/mission-preflight`):

| Piece | What it does | Required? | How it is set up |
|---|---|---|---|
| **Context7 MCP** | Agents verify current library, framework, MCP, plugin, and CLI versions before pinning or recommending them | **Mandatory** — a mission stops if it is missing | Hosted server `https://mcp.context7.com/mcp` (no Node). Claude: plugin `.mcp.json`. Antigravity: plugin `mcp_config.json`. OpenCode: merged into `opencode.json`. Codex: block in `.codex/config.toml`. An existing `context7` server of yours is left untouched. Optional `CONTEXT7_API_KEY` raises rate limits. |
| **Graphify** (`graphifyy` 0.9.95) | Indexes code into a lightweight graph; agents read the map instead of raw files, saving input tokens and API cost. Built **offline with no API key** (`graphify extract . --code-only`, then `graphify cluster-only . --no-label --no-viz`). On this repository `graphify benchmark` measured 11–25× fewer tokens per recon question. | Optional — **asked before installing** | `install.py` asks (or `--with graphify` / `--without graphify`); otherwise preflight asks inside the CLI. Installs with `uv tool`, then `pipx`, then `pip --user`. |
| **Terse output** | Cuts output tokens for background agent chatter. Rules derived from [Caveman](https://github.com/JuliusBrussee/caveman) v4.0.1 (Apache-2.0), bundled as the `terse-output` skill — nothing to download, no Node | Optional — **asked before enabling** | `install.py` asks (or `--with terse` / `--without terse`); otherwise preflight asks. |

Answers are stored per project in `.actionboard/preferences.json`.

**Never compressed:** mission briefs, mission plans, mission reports, source code, code comments,
commit messages, and security reviews are always written in full standard prose with every table
and field intact, whatever is enabled. Every agent report ends with a `Files created/changed:` list.

ActionBoard works with Caveman but is not Caveman and is not endorsed by its author.

## AI-ops maturity: every mission counts

At the end of every mission, Black Agent scores each dispatched assignment on the five formation
stages, records the run in `.actionboard/registry.json` (commit it: it is your evidence), and
adds a **Maturity & Progress Summary** to the mission report:

| Action | Tier (threshold) | Orchestrator | Data | Analysis | Action | Defense/Audit | Clean Run | Clean runs | Execution mode | Next milestone |
|---|---|---|---|---|---|---|---|---|---|---|
| Code implementation (`code-implementation`) | T1 (≥90%) | ✅ pass · 100% | ✅ pass · 67% | ✅ pass · 100% | ✅ pass · 100% | ✅ pass · 100% | Yes | 2/3 | Guided → **Actionlist** → Autonomous | Raise Data 67% → 90% (≈7 more passing run(s)), then reach 3 clean runs to unlock Autonomous. |

- Each kind of work (an action type such as `code-implementation`) earns autonomy separately:
  **Guided → Actionlist → Autonomous**, once every stage stays at or above the tier threshold
  and enough clean runs exist (T1: 90% and 3 runs, T2: 90% and 5, T3: 95% and 10; T4 never).
- Only the last 20 runs within 90 days count, so maturity also drops when quality drops.
- The numbers come from `maturity.py`, which uses the formation gate's own rules
  (`gate_check.py`). An unscored stage is a fail, and a retry-to-green fails the Action stage.
- Your operator level (L1–L7) is a certification you provide in `.actionboard/config.json`.
  Missions never raise it; it caps the highest tier that may run autonomously.

## Known gaps

| CLI | Gap | Effect |
|---|---|---|
| OpenCode 2.x | `opencode run "/start-mission …"` does not expand commands; the text goes to the default `build` agent, which implements directly with no go/no-go gate | Use `/start-mission` in the interactive TUI. For scripts, run `opencode run --agent black-agent "<objective and the start-mission text>"`. |
| OpenCode 1.x | Plugins cannot "ask" | OpenCode 2.x asks natively through its permission hook. On 1.x (legacy plugin) an ask is let through only for a plain `openshell …` command that the agents' `permission.bash` ask patterns catch; otherwise it is denied. |
| Codex | Hooks cannot "ask" | Same, with `.codex/rules/actionboard.rules` (`prompt`). `--add-endpoint …:full` is denied rather than asked. |
| Codex | No per-agent tool restriction | Read-only roles are enforced by instructions only. |
| Codex | Project hooks run only after a one-time `/hooks` trust | Until you trust them, the guard is off on Codex; the `.rules` prompts still apply. |
| Antigravity | `toolPermission: always-proceed` approves even a hook's `force_ask` | The guard denies its "ask" commands under that setting; run them yourself or switch to `request-review`. Runs started with `--mode auto` or `--dangerously-skip-permissions` may approve asks (denies still block). |
| Codex | No custom commands | `/start-mission` is the `$start-mission` skill; the session plays Black Agent. |
| Antigravity | No custom commands | `/start-mission` is a skill; the session plays Black Agent (also available as `agy --agent black-agent`). |
| All but Claude | `browser-actions` skill | Claude-only (Claude in Chrome); not shipped elsewhere. |

Full research and sources: [`docs/capability-matrix.md`](docs/capability-matrix.md).

## Development

```
src/          neutral source — edit here
adapters/     one adapter per CLI (+ shared hook adapter)
scripts/      build.py (src → dist), install.py
dist/         generated, committed, checked in CI — do not edit
tests/        guard, build/lint, installer, maturity, OpenCode plugin, live smoke results
```

```sh
python scripts/build.py --target all            # regenerate dist/
python scripts/build.py --check                 # what CI runs
python -m unittest discover -s tests/guard
python -m unittest discover -s tests/build
python -m unittest discover -s tests/install
python -m unittest discover -s tests/maturity
node --test tests/opencode/plugin.test.mjs      # Node 23.6+
```

Authoring rules for `src/`:

- Agent frontmatter: `name`, `description`, `role` (`primary`|`subagent`), `model_tier`
  (`strong`|`fast`|`inherit`), `capabilities` (`read`, `write`, `edit`, `bash`, `webfetch`,
  `websearch`, `delegate`, `skills`), optional `x-<cli>:` overrides.
- Skill frontmatter: `name`, `description`, optional `invocation` (`model`|`user`),
  `targets: [..]`, `x-claude:` (e.g. `allowed-tools`).
- Never name a CLI's tools in prose. Use `{{tool:dispatch}}`, `{{tool:read}}`, … ,
  `{{skill_dir}}`, `{{skills_root}}`, `{{args}}`, or a `<!-- only:<cli> -->` block.

Architecture decision: [`docs/adr/0001-src-dist-architecture.md`](docs/adr/0001-src-dist-architecture.md).
Plan and progress: [`PLAN.md`](PLAN.md).

## License

MIT
