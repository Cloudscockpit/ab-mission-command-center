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

| CLI | Start a mission | Status |
|---|---|---|
| Claude Code | `/start-mission <objective>` | Supported (parity with v0.6.1) |
| OpenCode | `/start-mission <objective>` | Supported, smoke-tested (agents load) |
| Codex CLI | `$start-mission <objective>` | Supported, built from docs (Codex not tested live) |
| Antigravity CLI (`agy`) | `/start-mission <objective>` | Supported, `agy plugin validate --strict` passes |

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

**Codex** — hooks must be trusted once with `/hooks` (Codex re-asks when they change).

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

## Known gaps

| CLI | Gap | Effect |
|---|---|---|
| OpenCode | Plugins cannot "ask" | An ask is let through only for a plain `openshell …` command that the agents' `permission.bash` ask patterns catch; otherwise it is denied. |
| Codex | Hooks cannot "ask" | Same, with `.codex/rules/actionboard.rules` (`prompt`). `--add-endpoint …:full` is denied rather than asked. |
| Codex | No per-agent tool restriction | Read-only roles are enforced by instructions only. |
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
tests/        guard, build/lint, installer, OpenCode plugin
```

```sh
python scripts/build.py --target all            # regenerate dist/
python scripts/build.py --check                 # what CI runs
python -m unittest discover -s tests/guard
python -m unittest discover -s tests/build
python -m unittest discover -s tests/install
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
