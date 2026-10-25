# Changelog

## 0.7.0 — unreleased

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

### Fixed
- Green Agent's "10–50× cheaper" claim replaced with the measured `graphify benchmark` figure,
  and its `/graphify` suggestions with the offline `graphify update .` / preflight.

### Changed
- Guard splits operator chains quote-aware (`sh -c 'a && openshell …'` is now evaluated instead of
  failing closed) and asks on `$(…)`, backticks, `eval`, `xargs`, `source`, and subshells that
  reach `openshell`.
- Agent prose names no CLI tools; each non-Claude agent gets a Tool glossary.

### Security
- Closed 16 guard bypasses found in review (background `&`, global flags before the
  subcommand, first-ask-hides-later-deny, `$VAR` expansion, `-lc`/`cmd /c` wrappers, unknown
  wrappers, pipes into shells, Windows paths, quote-split names, glued credential names,
  nesting depth). Any `openshell` word the parser cannot attribute now asks.
- Hooks fail closed on crashes, undecodable input, and missing Python on every CLI.
- Codex/OpenCode only hand an ask to static rules when the literal command matches them.
- Installer refuses paths with shell metacharacters, writes configs atomically, and never
  writes outside the target directory.
