# Changelog

## 1.1.0 — 2026-10-26

Zero-footprint install: no clone left in your project, and uninstall without a clone.

### Added
- `install.py --cleanup`: after a successful install, deletes the installer's own checkout
  (the `git clone --depth 1 … && python …/install.py --target <cli> --project . --cleanup`
  one-liner). Clears read-only git object files on Windows.
- `scripts/actionboard_uninstall.py`: standalone, standard-library uninstaller copied next to the
  install manifest for Codex, OpenCode and Antigravity
  (`.codex/actionboard/`, `.opencode/actionboard/`,
  `.agents/plugins/actionboard-v5-agentformation/`). It removes exactly the manifest's unchanged
  files with no clone present; the manifest now also records `project`.
- `@actionboard/install` npm package (`npx @actionboard/install --target <cli>`) and a
  standard-library Python wrapper for `uvx`, both downloading the tagged source into a temporary
  folder that is always removed.
- Tag-triggered release workflow that publishes to npm only when an `NPM_TOKEN` secret exists.

### Security
- `--cleanup` refuses (install left intact, exit 0) unless the checkout is a strict subfolder of
  the project, is a git work tree whose origin is Cloudscockpit/ab-mission-command-center, has no
  edits, untracked or ignored files, no unpushed commits or stashes, and holds no `--config` file.
- Wrappers extract archives safely (no path traversal) and download over HTTPS only.

### Fixed
- D1: uninstall left `__pycache__/` folders that Python created beside installed hook scripts, so
  a project never returned to its pre-install listing. Uninstall now removes a `__pycache__/` only
  when every entry is a `.pyc` of a script it installed.

### Known gaps / open
- Bundle checksum pin for the downloaded tarball (Medium) is not implemented yet.
- Smoke defects D2-D4 remain open; see `tests/smoke/results-2026-10-v1.1.md`.
- `npx` and `uvx` work only once v1.1.0 is tagged and published.
- Codex hook-layer guard still needs the one-time `/hooks` trust; Codex may need prompting to find
  Context7; OpenCode shows a generic "Permission denied: shell" on guard denials.

## 1.0.0 — 2026-10-25

Multi-CLI rebuild of ActionBoard V5 Agent Formation (from the Claude-only v0.6.1).

### Added
- Neutral `src/` with CLI-agnostic agent frontmatter, generated per CLI by `scripts/build.py`.
- Targets: Claude Code, OpenCode, Codex CLI, Antigravity CLI.
- `scripts/install.py` with CLI detection, project/global scope, manifest-tracked uninstall.
- Python hook core (`src/hooks/core/`) replacing the bash hooks; runs on Windows, macOS, Linux.
- `actionboard-kb` skill (the former `kb/mission-knowledge-format.md`).
- OpenCode: a `/command` for every user-invocable skill (`/mission-brief`, `/mission-plan`, …),
  since OpenCode does not list skills in the `/` menu. `/mission-harness` runs in
  `sandbox-warden` as a subtask, as on Claude Code.
- `sandbox-warden` may load skills (needed to run `/mission-harness`).
- CI: guard, build/drift/lint, installer, and OpenCode plugin tests on 3 OSes × Python 3.9–3.12.
- Cost and context layer:
  - **Context7 MCP is mandatory** on every CLI (hosted server, no Node); the installer adds it
    and never touches a `context7` server the user already configured. Missions stop without it.
  - `mission-preflight` skill (Step 0 of every mission): checks Context7, asks before installing
    Graphify, builds the code graph offline, asks before enabling terse output.
  - `terse-output` skill: output-token rules derived from Caveman v4.0.1 (Apache-2.0, LICENSE and
    NOTICE bundled), limited to agent chatter.
  - Shared operating policy in every agent: graph-first recon, Context7 version checks, terse
    chatter only when enabled, full prose for mission documents/code/commits/security reviews,
    and a `Files created/changed:` list at the end of every report.
  - `install.py --with graphify,terse` / `--without …`, with an explanatory note before each prompt.
  - Registry actions `version-lookup`, `mission-preflight`, `output-compression`.

- **AI-ops maturity from every mission:**
  - `actionboard-devops-mission/scripts/maturity.py`: `record` appends a scored run to
    `.actionboard/registry.json`; `summary` renders the Maturity & Progress Summary using the
    formation gate's own rules (stage scores, Clean Run, tier, `3/5` clean runs, Guided →
    Actionlist → Autonomous, next milestone with the number of runs needed).
  - Every mission report (the `mission-report` skill and the DevOps report template) now has a
    mandatory `## Maturity & Progress Summary` section, plus one `MaturityProgress` node per
    scored assignment in the JSON-LD.
  - Black Agent scores and records every mission at the end, whether or not it is written to disk.
  - Registry action `maturity-scoring`. Operator level stays a user-provided certification.

### Fixed
- **OpenCode 2.x:** the guard never fired, because 2.x removed `tool.execute.before` and renamed
  the shell tool to `shell`. New 2.x plugin uses `ctx.permission.hook("evaluate")` (native ask)
  and `ctx.tool.hook("execute.after")`; the 1.x plugin moved to `actionboard/legacy/` and
  `install.py` installs it only when it detects OpenCode 1.x. Verified live on 2.1.4.
- **Antigravity on Windows:** hooks failed because agy re-escapes quotes before `cmd /c`; the
  installer now writes the Python and hook paths unquoted unless they contain spaces (same for
  Codex `commandWindows`). Verified live on agy 1.4.7.
- **Live smoke round 1** (all four CLIs pass the full mission; `tests/smoke/results-2026-10.md`):
  - Claude Code: agents now list the Context7 MCP tools (preflight could not see Context7) and
    `PowerShell` next to `Bash` (on Windows the shell tool can be PowerShell); the guard hook
    matches `Bash|PowerShell`.
  - Claude Code: `/start-mission` makes the main session play Black Agent. As a subagent it
    rightly refused a relayed "go", so scoring never ran.
  - Antigravity agents set `inheritMcp: true`.
  - Preflight writes `.graphifyignore` so the graph covers the user's code, not agent tooling.
  - Maturity rubric: Yellow Agent's own work is verified by Black Agent re-running Yellow's
    exact test command (it could never pass the Action stage before).
  - README: `opencode run "/start-mission …"` does not expand commands on OpenCode 2.x.
- **Live smoke round 2:** preflight always ensures `.graphifyignore` (and rebuilds the graph when
  it adds lines); Green Agent confirms the test command's interpreter starts before handing it over;
  `maturity.py summary` prints one row per assignment when a mission scores the same action twice.
- Docs for 1.0.0: README lists the tested CLI versions and the new known gaps;
  `docs/capability-matrix.md` resolves every unverified item with evidence; `docs/index.html`
  covers all four CLIs and the `src/` authoring flow.
- Green Agent's "10–50× cheaper" claim replaced with the measured `graphify benchmark` figure,
  and its `/graphify` suggestions with the offline `graphify update .` / preflight.

### Changed
- Guard splits operator chains quote-aware (`sh -c 'a && openshell …'` is now evaluated instead of
  failing closed) and asks on `$(…)`, backticks, `eval`, `xargs`, `source`, and subshells that
  reach `openshell`.
- Agent prose names no CLI tools; each non-Claude agent gets a Tool glossary.

### Security
- **Antigravity hook auto-approved shell commands.** Its no-objection answer was `allow`, which
  agy documents as "automatically allow the tool execution", so every `run_command` skipped the
  user's own approval setting. It now answers `ask` (defers to that setting) and sends guard asks
  as `force_ask`. Under `toolPermission: always-proceed`, which approves even `force_ask`, guard
  asks are denied, as on Codex. Verified live on agy 1.4.7.
- Closed 16 guard bypasses found in review (background `&`, global flags before the
  subcommand, first-ask-hides-later-deny, `$VAR` expansion, `-lc`/`cmd /c` wrappers, unknown
  wrappers, pipes into shells, Windows paths, quote-split names, glued credential names,
  nesting depth). Any `openshell` word the parser cannot attribute now asks.
- Hooks fail closed on crashes, undecodable input, and missing Python on every CLI.
- Codex/OpenCode only hand an ask to static rules when the literal command matches them.
- Installer refuses paths with shell metacharacters, writes configs atomically, and never
  writes outside the target directory.
