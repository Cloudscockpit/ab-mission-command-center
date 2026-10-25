# Changelog

## 0.7.0 — unreleased

Multi-CLI rebuild of ActionBoard V5 Agent Formation (from the Claude-only v0.6.1).

### Added
- Neutral `src/` with CLI-agnostic agent frontmatter, generated per CLI by `scripts/build.py`.
- Targets: Claude Code, OpenCode, Codex CLI, Antigravity CLI.
- `scripts/install.py` with CLI detection, project/global scope, manifest-tracked uninstall.
- Python hook core (`src/hooks/core/`) replacing the bash hooks; runs on Windows, macOS, Linux.
- `actionboard-kb` skill (the former `kb/mission-knowledge-format.md`).
- CI: guard, build/drift/lint, installer, and OpenCode plugin tests on 3 OSes × Python 3.9–3.12.

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
