# ADR 0001 — Neutral `src/` → generated `dist/<target>/`

- Status: accepted
- Date: 2026-10-25

## Context

ActionBoard V5 Agent Formation v0.6.1 is a Claude Code plugin. Its agents use Claude
frontmatter, its prose names Claude tools, its skills resolve files through
`${CLAUDE_PLUGIN_ROOT}`, and its hooks follow the Claude stdin/stdout contract in bash.
We want the same mission flow on OpenCode, Codex CLI, and Antigravity CLI, with more CLIs
to follow.

## Decision

1. **One neutral source** in `src/`: agents with a CLI-agnostic frontmatter (`role`,
   `model_tier`, `capabilities`, optional `x-<target>` overrides), the start-mission
   command, Agent Skills, and a Python hook core.
2. **One adapter per CLI** in `adapters/<target>/adapter.py`, called by
   `scripts/build.py`, which writes `dist/<target>/`.
3. Prose stays neutral with three mechanisms, resolved at build time:
   - placeholders: `{{tool:dispatch}}`, `{{skill_dir}}`, `{{skills_root}}`, `{{args}}`;
   - conditional blocks: `<!-- only:claude -->…<!-- /only -->` and `<!-- not:claude -->…<!-- /not -->`;
   - a per-target **Tool glossary** appended to every non-Claude agent prompt,
     filtered to the agent's capabilities.
4. The hook core (`src/hooks/core/`) speaks a neutral JSON contract
   (`{command}` → `{decision, reason, rule, plain}`). Thin adapters translate native
   payloads: `adapters/common/hooks/cli_hook.py` (Claude, Codex, Antigravity) and
   `adapters/opencode/plugins/actionboard-guard.ts`.
5. `dist/` is **committed** and CI fails when it drifts from a fresh build. The committed
   `dist/` is the golden output; `tests/build` checks determinism, drift, and per-target
   schema lint, instead of a separate `tests/golden/` copy.
6. Install-time values (Python path, absolute hook paths) are tokens in `dist/`
   (`__PYTHON__`, `__HOOKS_DIR__`) filled by `scripts/install.py`, so `dist/` stays
   machine-independent.

## Consequences

- Adding a CLI is one adapter module, an entry in `build.TARGETS`, and a layout in
  `install.py`. Source files do not change unless the new CLI needs a conditional block.
- Contributors edit `src/` and run `python scripts/build.py`; editing `dist/` directly
  fails CI.
- Claude output differs from v0.6.1 only in wording (tool names via placeholders, the KB
  moved into the `actionboard-kb` skill); frontmatter, tools, models, and hooks behaviour
  match. The guard is stricter: it now also asks on `$(…)`, backticks, `eval`, `xargs`,
  `source`, and subshells that reach `openshell`, and splits operator chains quote-aware.
