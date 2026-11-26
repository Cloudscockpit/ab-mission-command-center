# actionboard-mcp

Connect any MCP client (Claude Code, Claude Desktop, Cursor, Codex, Antigravity, OpenCode) to ActionBoard with your own LLM subscription. The package ships two entry points over the same core:

- `actionboard-mcp`: an MCP server over stdio
- `ab`: a CLI that prints one JSON object per command

It reuses the ActionBoard CLI (`actionboard_cli`): browser sign-in, OS keychain token storage, the edge proxy, Pod token exchange and presigned S3 uploads.

## Tools

| Tool | What it does |
|---|---|
| `ab_auth_status` | Login state, token store, active Pod/Board and sync mode. It never returns tokens. |
| `ab_login(provider?)` | Opens the ActionBoard sign-in page in your browser and blocks until you finish (up to 5 min). It never takes a password. |
| `ab_logout` | Removes stored tokens. |
| `ab_list_pods` | Lists your Pods. |
| `ab_list_boards(pod_id)` | Lists Boards in a Pod (exchanges a Pod token on first use). |
| `ab_select_board(pod_id, board_id, sync?)` | Saves the active Pod/Board (and `ask`/`auto`/`off` sync) to `.actionboard/config.json`. |
| `ab_list_assigned(pod_id?, board_id?, invitation_status?)` | Lists missions assigned to you, plus your invitations. |
| `ab_fetch_mission(...)` | Writes the brief, plan and attachments to `docs/missions/<date>-<slug>/` and returns paths, not contents. |
| `ab_submit_mission(...)` | Uploads a mission folder. Unchanged files are skipped. `dry_run` previews the upload. |
| `ab_post_progress(...)` | Sets a linked mission's status and/or posts a comment. |

Fetched `mission-brief.md` / `mission-plan.md` keep the `BEGIN/END ACTIONBOARD_UNTRUSTED_…` markers. `ab_fetch_mission` returns `"untrusted_content": true`, which tells the model to treat that content as data, not instructions. `mission_dir` and `out_dir` must be inside the project directory.

## Install in your MCP client

Every snippet runs the server from GitHub with [uv](https://docs.astral.sh/uv/). The server reads and writes `.actionboard/` and `docs/missions/` in its **project directory**. That is the current directory unless you pass `--project-dir` (or set `ACTIONBOARD_PROJECT_DIR`). Clients that don't start servers in your project folder need `--project-dir`.

`ab_login` waits for you to finish signing in. If your client has a short tool timeout, sign in once from a terminal with `ab login` instead (see [CLI](#cli)). The tokens are shared.

### Claude Code

```sh
claude mcp add actionboard --scope project -- \
  uvx --from "git+https://github.com/Cloudscockpit/ab-mission-command-center#subdirectory=packages/actionboard-mcp" actionboard-mcp
```

This writes `.mcp.json` in the project root:

```json
{
  "mcpServers": {
    "actionboard": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/Cloudscockpit/ab-mission-command-center#subdirectory=packages/actionboard-mcp", "actionboard-mcp"]
    }
  }
}
```

### Claude Desktop

Edit `claude_desktop_config.json` (macOS: `~/Library/Application Support/Claude/`, Windows: `%APPDATA%\Claude\`). Desktop has no project folder, so pass one. If Desktop can't find `uvx`, use its absolute path (`which uvx`).

```json
{
  "mcpServers": {
    "actionboard": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/Cloudscockpit/ab-mission-command-center#subdirectory=packages/actionboard-mcp",
               "actionboard-mcp", "--project-dir", "/absolute/path/to/your/project"]
    }
  }
}
```

### Cursor

`.cursor/mcp.json` in the project:

```json
{
  "mcpServers": {
    "actionboard": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/Cloudscockpit/ab-mission-command-center#subdirectory=packages/actionboard-mcp",
               "actionboard-mcp", "--project-dir", "${workspaceFolder}"]
    }
  }
}
```

### Codex

`~/.codex/config.toml`. The longer tool timeout leaves room for `ab_login`.

```toml
[mcp_servers.actionboard]
command = "uvx"
args = ["--from", "git+https://github.com/Cloudscockpit/ab-mission-command-center#subdirectory=packages/actionboard-mcp",
        "actionboard-mcp", "--project-dir", "/absolute/path/to/your/project"]
tool_timeout_sec = 330
```

### Antigravity

**Agent panel → … → MCP Servers → Manage MCP Servers → View raw config** (`mcp_config.json`):

```json
{
  "mcpServers": {
    "actionboard": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/Cloudscockpit/ab-mission-command-center#subdirectory=packages/actionboard-mcp",
               "actionboard-mcp", "--project-dir", "/absolute/path/to/your/project"]
    }
  }
}
```

## CLI

```sh
uvx --from "git+https://github.com/Cloudscockpit/ab-mission-command-center#subdirectory=packages/actionboard-mcp" ab status
ab login                                   # browser sign-in
ab pods && ab boards --pod <podId>
ab select --pod <podId> --board <boardId> --sync auto
ab assigned
ab fetch --invitation-id <id> --accept --start
ab submit --mission-dir docs/missions/<dir> --dry-run
ab progress --mission-dir docs/missions/<dir> --comment "wave 1 done"
```

Exit codes: `0` ok, `1` error, `3` not logged in. Errors go to stderr.

## Settings

The server and CLI honor the same environment as `submit_mission.py`: `ACTIONBOARD_CREDENTIALS_FILE`, `ACTIONBOARD_EDGE_PROXY_URL`, `ACTIONBOARD_LOGIN_URL`, `ACTIONBOARD_KEYCHAIN=off` (file storage only), and so on. Tokens live in the OS keychain when one is available. Otherwise they go in `~/.actionboard/credentials.json` (mode 0600).

## Development

```sh
cd packages/actionboard-mcp
uv run --extra dev pytest                       # unit tests (HTTP, AppSync, S3 and keychain mocked)
uv run ab status                                # CLI against your real account
npx @modelcontextprotocol/inspector uv run actionboard-mcp   # poke the server interactively
```

`src/actionboard_mcp/_vendor/actionboard_cli/` is an exact copy of `src/skills/mission-report/scripts/actionboard_cli/`. That keeps the package installable on its own while the plugin keeps working unchanged. A test fails when the two drift. To resync from the repo root:

```sh
rsync -a --delete --exclude __pycache__ src/skills/mission-report/scripts/actionboard_cli/ \
  packages/actionboard-mcp/src/actionboard_mcp/_vendor/actionboard_cli/
```

Transport is isolated in `server.py:main()`. A Streamable HTTP entry point can serve the same `mcp` object later.
