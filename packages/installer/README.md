# @actionboard-ai/install

Zero-clone installer for ActionBoard on Codex, Antigravity and OpenCode. It downloads the matching release bundle into a temporary directory, runs the installer from it, and deletes the temp directory afterwards. Nothing is cloned into your project.

Claude Code is not installed this way. Use `/plugin marketplace add Cloudscockpit/ab-mission-command-center`.

## Requirements

- Python 3.9+ on PATH (`py -3`, `python3` or `python`), or set `ACTIONBOARD_PYTHON`. The interpreter path is written into installed hook commands, so use a permanent install, not a temporary virtualenv.
- Node 18+ for npx, or uv for uvx.

## Usage

```sh
npx @actionboard-ai/install --target codex            # current directory
npx @actionboard-ai/install --target opencode --project ./my-app --yes
npx @actionboard-ai/install --target antigravity --global
```

With uvx (before the tag is on PyPI, run it from git):

```sh
uvx --from "git+https://github.com/Cloudscockpit/ab-mission-command-center#subdirectory=packages/installer-py" actionboard-install --target codex
```

Options: `--target <codex|antigravity|opencode>`, `--global`, `--project DIR`, `--uninstall`, `--dry-run`, `--yes`, `--force`, `--with LIST`, `--without LIST`, `--version`, `--help`.

## Uninstall

```sh
npx @actionboard-ai/install --target codex --uninstall
```

This also removes installs made by 1.0.0.

## Environment

- `ACTIONBOARD_BUNDLE`: a local `.tar.gz` path or an https URL to use instead of `https://codeload.github.com/Cloudscockpit/ab-mission-command-center/tar.gz/refs/tags/v<version>`. Only https is accepted for remote bundles.
- `ACTIONBOARD_PYTHON`: Python executable to use.

If the release tag has not been published yet you will see `release v<version> not found - tag not published yet`.
