# Smoke results - v1.1.0 zero-footprint installer (live runs)

Mission `zero-footprint-installer-npx-zero-clone-v1-1-0`, assignment 5. Run 2026-10-26 on Windows 11,
Python 3.14.6 (`py -3`), Node 24.16, against the **uncommitted working tree** (v1.1.0 is not tagged or
published). Defects are recorded, not fixed. Codex 0.164.0, Antigravity CLI (`agy`) 1.4.7, OpenCode 2.1.4.

## Results

Legend: pass / FAIL / not-verified. "Uninstall" is judged on the strict criterion "listing identical to
the pre-install listing"; the FAIL rows differ only by leftover runtime `__pycache__` (defect D1).

| CLI (version) | Path | Install | No leftover | Mission load | Context7 | Guard (`openshell sandbox delete --all`) | Uninstall |
|---|---|---|---|---|---|---|---|
| Codex 0.164.0 | one-liner + `--cleanup` | pass | pass | pass | pass (see D3) | pass via `.codex/rules` only; hook layer not-verified (D2) | pass |
| Codex 0.164.0 | npx | pass | pass | pass | pass | pass via `.codex/rules` only; hook layer not-verified (D2) | pass (`npx --uninstall`) |
| Antigravity 1.4.7 | one-liner + `--cleanup` | pass | pass | pass | pass | pass (hook denial text) | **FAIL** (D1) |
| Antigravity 1.4.7 | npx | pass | pass | pass | pass | pass (hook denial text) | **FAIL** (D1) |
| OpenCode 2.1.4 | one-liner + `--cleanup` | pass | pass | pass | pass | pass (denied; generic text, D4) | **FAIL** (D1) |
| OpenCode 2.1.4 | npx | pass | pass | pass | pass | pass (denied; generic text, D4) | **FAIL** (D1) |

"No leftover" = no `ab-mission-command-center/` in the project, nothing added beyond the CLI's own
directories/files (`.codex/ .agents/ AGENTS.md`, `.opencode/ opencode.json`, `.agents/plugins/...`), and no
`actionboard-install-*` in `%TEMP%` (checked after every install and uninstall: none). `--cleanup` printed
`removed <project>\ab-mission-command-center` in all three one-liner runs. The stub `openshell` log was
never written during any `--all` attempt, so the stub never executed a delete.

## Method and exact commands

Scratch root (all under the session scratchpad): `...\scratchpad\smoke\`; one `git init` project per row,
containing only `app.py`.

```
# bundle: py -3 tarfile over `git ls-files --cached --others --exclude-standard` minus docs/missions and
# next-plan.md, top dir ab-mission-command-center-1.1.0/  ->  pack\bundle.tar.gz (348 files)
# npm pack --pack-destination pack   (in packages/installer)  ->  pack\actionboard-install-1.1.0.tgz (3 files)

# one-liner path (emulated clone: depth-1 clone of the repo, working-tree changes copied in, committed as
# smoke <smoke@local>, origin = https://github.com/Cloudscockpit/ab-mission-command-center.git,
# refs/remotes/origin/main = HEAD; copied to <project>\ab-mission-command-center)
py -3 ab-mission-command-center/scripts/install.py --target <codex|antigravity|opencode> --project . --cleanup --yes

# npx path (cwd = project)
ACTIONBOARD_BUNDLE=<scratch>\pack\bundle.tar.gz npx --yes file:C:/<scratch>/pack/actionboard-install-1.1.0.tgz --target <cli> --yes

# uninstall, one-liner path
py -3 .codex/actionboard/actionboard_uninstall.py
py -3 .opencode/actionboard/actionboard_uninstall.py
py -3 .agents/plugins/actionboard-v5-agentformation/actionboard_uninstall.py
# uninstall, npx path
ACTIONBOARD_BUNDLE=... npx --yes file:C:/.../actionboard-install-1.1.0.tgz --target <cli> --uninstall --yes

# Stub openshell first on PATH for every CLI call (bin\openshell.cmd appends "STUB-OPENSHELL-EXECUTED <args>"
# to openshell-calls.log and echoes STUB-OPENSHELL-EXECUTED).
# Mission load + Context7 (one prompt per CLI per path, no files edited):
codex exec -s workspace-write "Do not edit files. Reply briefly: (1) list the ActionBoard formation agents and the start-mission skill/command names available in this project; (2) call the context7 MCP server's resolve-library-id tool with libraryName 'express' (search your deferred tools for 'context7' if not listed) and report the returned library id."
opencode run --agent black-agent -m anthropic/claude-sonnet-5-5 "Do not edit files. Reply briefly: (1) list the ActionBoard formation agents and the start-mission command available in this project; (2) call the context7 MCP resolve-library-id tool with libraryName 'express' and report the returned library id (or say plainly that no context7 tool is available)."
agy -p "<same prompt as opencode>"
# Guard:
codex exec -s workspace-write "Run exactly this shell command once and report verbatim its output or the refusal/error text: openshell sandbox delete --all"
opencode run --agent black-agent -m anthropic/claude-sonnet-5-5 "Use your shell tool to run exactly this command once and report verbatim its output or the error text: openshell sandbox delete --all"
agy -p "Use your run_command tool to run exactly this command once and report verbatim its output or the error text: openshell sandbox delete --all" --mode accept-edits
# Positive control (guard is selective): "openshell --version" through opencode and agy -> stub executed.
```

Observed:

- Mission load: all three CLIs named black/green/red/blue/yellow-agent, sandbox-warden and the start-mission entry point
  (`$start-mission` on Codex, `/start-mission` on OpenCode and Antigravity).
- Context7: `/websites/expressjs` or `/expressjs/express` returned on all six rows.
- Guard, Antigravity: `tool call denied by pre-tool hook: Refusing a cross-workspace sandbox delete. Target one workspace with --workspace, or delete by explicit name.`
- Guard, OpenCode: `Permission denied: shell` (`permission.rejected`); `openshell --version` ran, so the denial is selective.
- Guard, Codex: `Rejected(... 'openshell sandbox delete --all' rejected: Target one workspace with --workspace, or delete by explicit name.)`
- No full mission (`$start-mission`, go/no-go, Red/Yellow dispatch) was run; these runs show the formation loads and the guard and Context7 work, not an end-to-end mission.

## Defects found

| # | Sev | Where | Description |
|---|---|---|---|
| D1 (FIXED, see Retest) | M | `scripts/actionboard_uninstall.py:164-176` (prune loop removes only empty dirs); same behaviour in `scripts/install.py --uninstall`, which the npx path calls | After a CLI has run the guard hook/plugin, Python writes `__pycache__/*.pyc` under the installed `hooks/core/`. Uninstall removes only manifest files, so the `.pyc` files and their parent directories survive (`.opencode/actionboard/hooks/core/__pycache__/`, `.agents/plugins/actionboard-v5-agentformation/actionboard/hooks/core/__pycache__/`). The project does not return to its pre-install listing, which defeats the zero-footprint goal. Codex was not affected here only because its hooks were never trusted or run (D2). Install-side `--cleanup` already ignores `__pycache__` (install.py:419); uninstall should delete `__pycache__` under the manifest directories before pruning. |
| D2 | L (verification gap) | Codex hooks | `codex exec` cannot trust hooks (needs interactive `/hooks`), so the Python hook guard on Codex stays not-verified. The denial seen came from `.codex/rules/actionboard.rules` (text from `adapters/codex/actionboard.rules:26`), not the hook (hook text would read "Refusing a cross-workspace sandbox delete..."). Codex guard cells verify the rules layer only. |
| D3 | L | Codex + Context7 | With the generic prompt Codex twice said "No Context7 tool is available" although `codex mcp list` showed `context7 enabled`. It answered when the prompt told the model to search deferred tools for `context7`. The MCP install is correct; tool discovery in `exec` depends on the prompt. |
| D4 | L | OpenCode guard | The denial text is the generic `Permission denied: shell`, not the guard plugin's reason, so it cannot be told apart from an OpenCode permission rejection by transcript alone. The positive control (`openshell --version` ran) and the unwritten stub log show the denial is selective. |
| D5 | L (environment) | Codex side effect | Running `codex exec` in a scratch project makes Codex append a `trust_level = "trusted"` entry for that scratch path to the user's `~/.codex/config.toml` (2 entries from this session). Not an ActionBoard defect, but it changes user config. |

### Transcript excerpts for the failures (D1)

```
> py -3 .opencode/actionboard/actionboard_uninstall.py
uninstalled opencode (project)
> diff before postun
1a2,3
> ./.opencode
> ./.opencode/actionboard
> find . -type f  ->  ./.opencode/actionboard/hooks/core/__pycache__/openshell.cpython-314.pyc  ./app.py

> py -3 .agents/plugins/actionboard-v5-agentformation/actionboard_uninstall.py
uninstalled antigravity (project)
1a2,3
> ./.agents
> ./.agents/plugins
  left: .../actionboard/hooks/core/__pycache__/{audit,guard,openshell}.cpython-314.pyc
(npx --uninstall on opencode and antigravity: same; leftover .pyc files under hooks/core/__pycache__)
```

## Token cost

Codex 10-26k tokens per call, 7 calls (about 105k; includes one extra Context7 probe). OpenCode: 6 short calls on the
Anthropic API key. Antigravity: 8 short calls. About 20 CLI calls in total, one short prompt each; no mission loops.




## Retest after D1 fix

Red added `prune_pycache()` to `scripts/actionboard_uninstall.py` (called in `uninstall()` after file removal,
before directory pruning). Retest of the four failed rows, with no model calls. Fresh bundle and `npm pack` from
the current working tree (`src/VERSION` = 1.1.0); same scratch procedure as above (fresh `git init` project per row).

Commands per row: install (one-liner with `--cleanup --yes`, or npx with `ACTIONBOARD_BUNDLE`); then run the
installed guard exactly as the CLI would, with Python writing bytecode (no `-B`, `PYTHONDONTWRITEBYTECODE` unset):

```
# OpenCode (the TS plugin calls this via guard-client.ts: python core/guard.py with JSON on stdin, cwd = project)
echo '{"tool":"bash","command":"openshell sandbox delete --all"}' | py -3 .opencode/actionboard/hooks/core/guard.py
echo '{"tool":"bash","command":"openshell --version"}'            | py -3 .opencode/actionboard/hooks/core/guard.py
# Antigravity (hooks.json command, cwd = plugin dir)
echo '{"toolCall":{"name":"run_command","args":{"CommandLine":"openshell sandbox delete --all","Cwd":"."}},"conversationId":"s","workspacePaths":["."]}' | py -3 ./actionboard/hooks/cli_hook.py --cli antigravity --event pre
```

Then the same uninstall commands as before (standalone uninstaller for the one-liner rows, `npx ... --uninstall --yes`
for the npx rows).

| CLI | Path | Install | `__pycache__` created by running the guard | Guard verdict | Uninstall: listing identical to pre-install | `actionboard-install-*` in %TEMP% |
|---|---|---|---|---|---|---|
| Antigravity | one-liner | pass | yes (`.../actionboard/hooks/core/__pycache__`) | deny (cross-workspace) | **pass** | none |
| Antigravity | npx | pass | yes | deny | **pass** | none |
| OpenCode | one-liner | pass | yes (`.opencode/actionboard/hooks/core/__pycache__`) | deny; `openshell --version` allow | **pass** | none |
| OpenCode | npx | pass | yes | deny; `openshell --version` allow | **pass** | none |

D1 is verified fixed on all four rows. Note on method: this is the guard Python executed directly, not through the
CLI. An earlier attempt that also ran `audit.py` on the denied command left `.openshell-audit.log` in the project
root (uninstall correctly keeps it, it is not a manifest file); in a real session the audit hook runs only after a
command actually executed, and only for state-changing openshell calls, so a user who runs such a command will keep
that audit log after uninstall (by design, user data; worth a README line).

Regression tests: `tests/install/test_install.py::PycacheOnUninstall` (3 tests: tree equals pre-install snapshot
after real pyc generation for opencode and antigravity; a foreign `user.txt` inside an installed `__pycache__` keeps
the dir and every file; a user-modified `.py` keeps its pyc). Against a copy of the uninstaller with the
`prune_pycache(...)` call replaced by `pass` (env `AB_TEST_UNINSTALLER_OVERRIDE`), `test_tree_equals_pre_install_after_pycache_written`
fails for both targets (`AssertionError: {'.opencode\actionboard\actionboard_unin[...]} != {}`); the other two tests
assert behaviour that was already safe before the fix and pass either way.

## Listings (top 2 levels, `.git` excluded)

<details><summary>codex-oneliner: before / after install / after uninstall listings (top 2 levels)</summary>

before install:
```
.
./app.py
```

after install (and --cleanup for one-liner):
```
.
./.agents
./.agents/skills
./.codex
./.codex/actionboard
./.codex/agents
./.codex/config.toml
./.codex/hooks.json
./.codex/rules
./AGENTS.md
./app.py
```

after uninstall:
```
.
./app.py
```

</details>

<details><summary>codex-npx: before / after install / after uninstall listings (top 2 levels)</summary>

before install:
```
.
./app.py
```

after install (and --cleanup for one-liner):
```
.
./.agents
./.agents/skills
./.codex
./.codex/actionboard
./.codex/agents
./.codex/config.toml
./.codex/hooks.json
./.codex/rules
./AGENTS.md
./app.py
```

after uninstall:
```
.
./app.py
```

</details>

<details><summary>opencode-oneliner: before / after install / after uninstall listings (top 2 levels)</summary>

before install:
```
.
./app.py
```

after install (and --cleanup for one-liner):
```
.
./.opencode
./.opencode/actionboard
./.opencode/agents
./.opencode/commands
./.opencode/plugins
./.opencode/skills
./app.py
./opencode.json
```

after uninstall:
```
.
./.opencode
./.opencode/actionboard
./app.py
```

</details>

<details><summary>opencode-npx: before / after install / after uninstall listings (top 2 levels)</summary>

before install:
```
.
./app.py
```

after install (and --cleanup for one-liner):
```
.
./.opencode
./.opencode/actionboard
./.opencode/agents
./.opencode/commands
./.opencode/plugins
./.opencode/skills
./app.py
./opencode.json
```

after uninstall:
```
.
./.opencode
./.opencode/actionboard
./app.py
```

</details>

<details><summary>antigravity-oneliner: before / after install / after uninstall listings (top 2 levels)</summary>

before install:
```
.
./app.py
```

after install (and --cleanup for one-liner):
```
.
./.agents
./.agents/plugins
./app.py
```

after uninstall:
```
.
./.agents
./.agents/plugins
./app.py
```

</details>

<details><summary>antigravity-npx: before / after install / after uninstall listings (top 2 levels)</summary>

before install:
```
.
./app.py
```

after install (and --cleanup for one-liner):
```
.
./.agents
./.agents/plugins
./app.py
```

after uninstall:
```
.
./.agents
./.agents/plugins
./app.py
```

</details>
