# Manual smoke tests

Automated tests cover the guard, build, installer, and the OpenCode plugin. These steps
need a real CLI and a model, so they are run by hand before a release. Use a scratch repo.

Objective for every CLI: `add a /hello endpoint that returns {"hello": "world"}`.

| # | CLI | Steps | Pass when |
|---|---|---|---|
| 4.3 | Claude Code | `/plugin marketplace add <this repo>`, `/plugin install actionboard-v5-agentformation@actionboard-v5-agentformation`, `/start-mission <objective>` | Four-part report, stops at go/no-go; Green ran as a separate agent. Then run `openshell sandbox delete --all` via the agent: denied. |
| 4.4 | Claude Code | Same objective on v0.6.1 | Report sections and agent roster match. |
| 5.8 | OpenCode | `python scripts/install.py --target opencode --project .`, `opencode`, `/start-mission <objective>`, reply `go` | Black dispatches `green-agent` via `task`, then red/yellow after go; guard throws on `openshell sandbox delete --all`. |
| 6.6 | Codex CLI | `python scripts/install.py --target codex --project .`, trust hooks with `/hooks`, `$start-mission <objective>`, `go` | `spawn_agent` used with `green-agent`; guard denies `openshell sandbox delete --all`; `openshell workspace delete x` prompts via rules. |
| 7.6 | Antigravity | `python scripts/install.py --target antigravity --project .`, `agy`, `/start-mission <objective>`, `go` | `invoke_subagent` used; guard asks on `openshell workspace delete x`, denies `--all`. |

Record results (CLI version, date, pass/fail, notes) in the release PR.
