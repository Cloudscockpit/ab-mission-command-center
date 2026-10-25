# ActionBoard Agent Formation — Multi-CLI Rebuild Plan

> Status: In progress · Owner: AbirZayn · Created: 2026-10-25
>
> Progress (2026-10-25): Phases 0–9 implemented locally. Open: 0.2 (GitHub repo — needs approval),
> live smoke tests 4.3/4.4/5.8/6.6/7.6 (see `tests/smoke/README.md`), 8.4 (npx/uvx), 10.2, 10.3 tag, 10.4.
> Capability matrix with sources: `docs/capability-matrix.md`.

---

## 1. Goal

Rebuild the **ActionBoard V5 Agent Formation** plugin from scratch as a
**CLI-agnostic** package that works on:

| Target | Priority |
|---|---|
| Claude Code | P0 (parity with current plugin) |
| OpenCode | P0 |
| Codex CLI | P1 |
| Antigravity CLI | P1 |

Same mission flow on every CLI:

1. Black Agent drafts **Mission Brief**
2. Green Agent runs **recon**
3. Black Agent drafts **Agent Assignments** (with file ownership)
4. **Skills Gap** analysis
5. **Risk Register**
6. **Go/no-go gate** → user approves → Red/Blue/Yellow execute
7. **Mission Report** (Markdown + schema.org JSON-LD)

Non-goals for v1: new mission features, UI changes, changes to the
JSON-LD format. This is a portability rebuild, not a redesign.

---

## 2. Source and Target Repos

| | Repo | Notes |
|---|---|---|
| Source (reference only) | `github.com/Cloudscockpit/actionboard-build-mission-pipeline` (v0.6.1) | Claude-only. Stays untouched; current users keep using it. |
| New | `C:\office-work\agent-formation` → `github.com/Cloudscockpit/ab-mission-command-center` (private) | Multi-CLI. Local only until push is approved. |

### What the source repo contains

| Part | Count | Portable? | Blocker |
|---|---|---|---|
| `skills/*/SKILL.md` | 13 | Mostly | `${CLAUDE_PLUGIN_ROOT}` used ~24 times |
| `agents/*.md` | 6 | No | Claude frontmatter (`tools`, `model: opus`, `color`) |
| `commands/start-mission.md` | 1 | No | Says "invoke via the `Agent` tool" |
| `hooks/` (2 bash scripts + `hooks.json`) | 2 | No | Claude stdin/stdout hook contract; bash-only (no Windows) |
| `kb/`, Python scripts, policy YAML | — | Yes | Paths must resolve without env var |
| `.claude-plugin/*.json` | 2 | No | Claude-only manifest |

Prose also references Claude-only names: `Agent` tool, `Skill` tool,
`/reload-plugins`, `skill-creator`.

---

## 3. Architecture Decision

**Chosen: neutral `src/` → generated `dist/<target>/`.**

Why: new repo has no existing users to protect, so we avoid making
Claude the "real" version. One source of truth, one adapter per CLI.

```
agent-formation/
├── PLAN.md                     ← this file
├── README.md                   ← compat matrix + install per CLI
├── src/
│   ├── agents/                 ← neutral frontmatter (superset)
│   ├── commands/               ← start-mission etc.
│   ├── skills/                 ← Agent Skills format, relative paths
│   ├── kb/                     ← shared knowledge (or folded into a skill)
│   └── hooks/core/guard.py     ← CLI-agnostic guard + audit logic
├── adapters/
│   ├── claude/                 ← manifest, hooks.json, bash shim
│   ├── opencode/               ← agent/command mapping, TS plugin
│   ├── codex/                  ← TBD after Phase 0
│   └── antigravity/            ← TBD after Phase 0
├── scripts/
│   ├── build.py                ← src → dist/<target>
│   └── install.py              ← copy dist/<target> into user/project
├── dist/                       ← generated, committed, CI-checked
└── tests/
    ├── guard/                  ← unit tests for guard.py
    ├── golden/                 ← expected build output per target
    └── smoke/                  ← per-CLI mission run scripts
```

### Neutral agent frontmatter (proposal)

```yaml
---
name: green-agent
description: Recon specialist ...
role: subagent            # primary | subagent
model_tier: fast          # strong | fast | inherit
capabilities:             # mapped per CLI
  read: true
  write: false
  edit: false
  bash: ask
  web: true
  delegate: false         # may dispatch other agents
  skills: true
---
```

Mapping examples:

| Neutral | Claude Code | OpenCode |
|---|---|---|
| `role: primary` | normal agent | `mode: primary` |
| `role: subagent` | normal agent | `mode: subagent` |
| `model_tier: strong` | `model: opus` | configurable `provider/model` or omit |
| `capabilities.write: false` | omit `Write`/`Edit` from `tools` | `permission.edit: deny` |
| `capabilities.bash: ask` | `Bash` in `tools` | `permission.bash: ask` |

---

## 4. Capability Matrix

✅ verified · ⚠️ needs verification in Phase 0 · ❌ not supported

| Capability | Claude Code | OpenCode | Codex CLI | Antigravity CLI |
|---|---|---|---|---|
| Skills (`SKILL.md`) | ✅ | ✅ (`.opencode/skills`, `.claude/skills`, `.agents/skills`) | ⚠️ | ⚠️ |
| Custom agents / subagents | ✅ | ✅ (`.opencode/agents/*.md`) | ⚠️ | ⚠️ |
| Nested delegation (Black → others) | ✅ | ⚠️ (Black as `primary`) | ⚠️ | ⚠️ |
| Slash commands with args | ✅ | ✅ (`.opencode/commands/*.md`, `$ARGUMENTS`) | ⚠️ (custom prompts?) | ⚠️ |
| Pre-tool hook (block) | ✅ | ✅ (`tool.execute.before`, throw) | ⚠️ | ⚠️ |
| Pre-tool hook ("ask") | ✅ | ❌ → use `permission.bash: ask` | ⚠️ | ⚠️ |
| Post-tool hook (audit) | ✅ | ✅ (`tool.execute.after`) | ⚠️ | ⚠️ |
| Per-agent model | ✅ | ✅ | ⚠️ | ⚠️ |
| Project context file | `CLAUDE.md` | `AGENTS.md` | `AGENTS.md` | ⚠️ |

**Fallback rule:** if a CLI has no subagents, run in **sequential role
mode** — one agent plays Black → Green → Red/Blue → Yellow in turn.
File ownership and the go/no-go gate still apply; only parallelism is lost.

---

## 5. Step-by-Step Working List

### Phase 0 — Research & Repo Setup (1–2 days)

- [x] 0.1 `git init` in `C:\office-work\agent-formation`, add `.gitignore`, `LICENSE` (MIT), this `PLAN.md`
- [ ] 0.2 Create GitHub repo (name TBD) — **do not push until approved**
- [x] 0.3 Verify **Codex CLI** current docs: skills location, subagents, custom prompts/commands, hooks, `AGENTS.md`, config file format
- [x] 0.4 Verify **Antigravity CLI** current docs: same checklist as 0.3
- [x] 0.5 Re-confirm **OpenCode**: nested subagent calls, plugin install via `opencode.json` vs `.opencode/plugins/`
- [x] 0.6 Fill every ⚠️ in Section 4 with ✅ / ❌ + doc link
- [x] 0.7 Decide fallback per gap (sequential mode, static permission rules, etc.)
- [x] 0.8 Write `docs/adr/0001-src-dist-architecture.md`

**Exit:** capability matrix has no ⚠️ left.

### Phase 1 — Neutral Source (2 days)

- [x] 1.1 Copy `skills/`, `kb/`, Python scripts, policy YAML from source repo into `src/`
- [x] 1.2 Replace every `${CLAUDE_PLUGIN_ROOT}/...` with skill-relative paths
- [x] 1.3 Move `kb/` files into the skills that use them, or into a shared `actionboard-kb` skill
- [x] 1.4 Make scripts resolve their own location (`__file__` / `$0`), no env vars
- [x] 1.5 Rewrite 6 agents with neutral frontmatter (Section 3)
- [x] 1.6 Rewrite prose to be tool-neutral: "dispatch the `green-agent` subagent" instead of "use the `Agent` tool"
- [x] 1.7 Mark platform-only lines with a conditional block, e.g. `<!-- only:claude -->...<!-- /only -->`
- [x] 1.8 Rewrite `commands/start-mission.md` in neutral form
- [x] 1.9 `grep -r "CLAUDE_PLUGIN_ROOT\|Agent tool\|Skill tool" src/` returns nothing

**Exit:** `src/` contains zero CLI-specific references outside conditional blocks.

### Phase 2 — Hook Core (2 days)

- [x] 2.1 Port guard logic from `hooks/guard-openshell.sh` into `src/hooks/core/guard.py`
  - Input: `{ "tool": "bash", "command": "..." }`
  - Output: `{ "decision": "allow|ask|deny", "reason": "..." }`
- [x] 2.2 Port audit logic from `hooks/audit-policy.sh` into `src/hooks/core/audit.py`
- [x] 2.3 Keep **fail-closed** behavior (unparseable + mentions openshell → ask/deny)
- [x] 2.4 Unit tests: quote bypass (`--all-work"spaces"`), `--flag=value`, `bash -c`, `VAR=x` prefix, operator chains, credential env vars, missing python
- [x] 2.5 Runs on Windows, macOS, Linux (Python 3.9+ only, no bash dependency)

**Exit:** `pytest tests/guard` green on all 3 OSes.

### Phase 3 — Build System (2 days)

- [x] 3.1 `scripts/build.py --target <claude|opencode|codex|antigravity|all>`
- [x] 3.2 Frontmatter mapper per target (Section 3 table)
- [x] 3.3 Conditional-block stripper (`only:<target>`)
- [x] 3.4 Per-target tool glossary injected into agent prompts (e.g. Claude `Agent` = OpenCode `task`)
- [x] 3.5 Model tier → model ID map, user-overridable via `agentformation.config.json`
- [x] 3.6 Single version source (`src/VERSION`) stamped into every manifest
- [x] 3.7 Golden-file tests in `tests/golden/<target>/`

**Exit:** `python scripts/build.py --target all` is deterministic and matches golden files.

### Phase 4 — Claude Code Adapter (1 day)

- [x] 4.1 Generate `.claude-plugin/plugin.json` + `marketplace.json` (source → `./dist/claude`)
- [x] 4.2 Generate `hooks/hooks.json` + thin shim that calls `guard.py` and emits `hookSpecificOutput.permissionDecision`
- [ ] 4.3 Smoke test: `/plugin install` from local marketplace → `/start-mission "add a hello endpoint"`
- [ ] 4.4 Compare output with old plugin v0.6.1 (parity check)

**Exit:** behavior matches v0.6.1.

### Phase 5 — OpenCode Adapter (2 days)

- [x] 5.1 Agents → `.opencode/agents/*.md` (`mode`, `model`, `permission`)
- [x] 5.2 Black Agent as `mode: primary` (or `all`) so it can dispatch the others
- [x] 5.3 Command → `.opencode/commands/start-mission.md` with `agent: black-agent`
- [x] 5.4 Skills → `.opencode/skills/` (or rely on `.agents/skills/`)
- [x] 5.5 Plugin `actionboard-guard.ts`: `tool.execute.before` on `bash` → call `guard.py` → throw on deny
- [x] 5.6 "ask" decisions → static `permission.bash` ask patterns in agent frontmatter
- [x] 5.7 `tool.execute.after` → `audit.py`
- [ ] 5.8 Smoke test full mission flow

**Exit:** full mission runs end-to-end in OpenCode, guard blocks a test command.

### Phase 6 — Codex CLI Adapter (2–3 days, scope set by Phase 0)

- [x] 6.1 Skills install location
- [x] 6.2 Agents → native subagents **or** sequential role mode
- [x] 6.3 `start-mission` → custom prompt/command equivalent
- [x] 6.4 Guard → hook if supported, else static sandbox/approval config + documented gap
- [x] 6.5 `AGENTS.md` snippet describing the formation
- [ ] 6.6 Smoke test

### Phase 7 — Antigravity CLI Adapter (2–3 days, scope set by Phase 0)

- [x] 7.1 – 7.6 Same checklist as Phase 6

### Phase 8 — Installer (1 day)

- [x] 8.1 `scripts/install.py --target <cli> [--global | --project <path>]`
- [x] 8.2 Detect installed CLIs automatically, prompt for which to install
- [x] 8.3 `--uninstall` removes only files it created (tracked in a manifest)
- [ ] 8.4 Optional: publish as `npx` / `uvx` package

### Phase 9 — CI & Quality (1–2 days)

- [x] 9.1 GitHub Actions matrix: ubuntu / macos / windows × python 3.9–3.12
- [x] 9.2 Jobs: guard unit tests, golden build tests, `dist/` drift check (`build.py && git diff --exit-code`)
- [x] 9.3 Lint: markdown frontmatter schema validation per target
- [x] 9.4 Security review of hook core (fail-closed, no shell injection)

### Phase 10 — Docs & Release (1 day)

- [x] 10.1 `README.md`: what it is, compat matrix, install per CLI, known gaps
- [ ] 10.2 `docs/` site (port `docs/index.html`)
- [x] 10.3 `CHANGELOG.md`, tag `v1.0.0`
- [ ] 10.4 Add deprecation/migration note to old repo README pointing here

---

## 6. Timeline

| Phase | Days |
|---|---|
| 0 Research & setup | 1–2 |
| 1 Neutral source | 2 |
| 2 Hook core | 2 |
| 3 Build system | 2 |
| 4 Claude adapter | 1 |
| 5 OpenCode adapter | 2 |
| 6 Codex adapter | 2–3 |
| 7 Antigravity adapter | 2–3 |
| 8 Installer | 1 |
| 9 CI & quality | 1–2 |
| 10 Docs & release | 1 |
| **Total** | **~17–21 days** |

---

## 7. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Codex / Antigravity lack subagents | H | Sequential role mode fallback |
| Nested delegation differs per CLI | H | Black Agent as primary; verify in Phase 0 |
| No "ask" decision outside Claude | M | Deny + reason, plus static permission ask-patterns |
| CLI without hooks → guard not enforced | M | Static deny rules + clear doc of gap |
| Model IDs differ per provider | M | `model_tier` + user-overridable map |
| CLI formats change (fast-moving tools) | M | Adapters isolated; golden tests catch drift; pin tested CLI versions in README |
| `dist/` drifts from `src/` | L | CI drift check |
| Python not installed on user machine | L | Installer checks; document requirement |

---

## 8. Open Decisions

- [ ] GitHub repo name and org
- [ ] Package name for installer (`@actionboard/agentformation`?)
- [ ] Commit `dist/` to git, or build on release only?
- [ ] Default model map for non-Anthropic providers
- [ ] Keep OpenShell sandbox features in v1 for all CLIs, or Claude/OpenCode only?

---

## 9. Definition of Done (v1.0.0)

- [x] Same `/start-mission` flow works on all 4 CLIs (or documented fallback) — two live missions
  per CLI ([`tests/smoke/results-2026-10.md`](tests/smoke/results-2026-10.md)); Codex uses the
  `$start-mission` skill, OpenCode needs the TUI (README Known gaps)
- [ ] Guard blocks blast-radius OpenShell commands on every CLI that has hooks — live on Claude
  Code, OpenCode 2.x and Antigravity; **Codex pending** its one-time interactive `/hooks` trust
  ([capability matrix, Open item](docs/capability-matrix.md#open-item))
- [x] CI green on Windows, macOS, Linux (`.github/workflows/ci.yml`, Python 3.9–3.12)
- [x] README has install steps + known gaps per CLI
- [ ] Old repo points to new repo — PR drafted
  ([`deprecation-pr.md`](docs/missions/2026-10-25-verify-and-release-multi-cli-agent-formation-v1/deprecation-pr.md)),
  waiting for approval to open it
