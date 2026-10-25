---
name: mission-preflight
description: Prepare a project for a cost-efficient ActionBoard mission — verify the mandatory Context7 MCP, offer to install Graphify and build an offline code graph, and offer terse agent output. Asks before installing or enabling anything. Use at Step 0 of every ActionBoard mission, or when the user asks to set up or check ActionBoard cost optimisation.
---

# Mission preflight

Run once at the start of a mission (Black Agent, Step 0). Each check is fast when it has already
passed. Write this report in full prose; it is a mission document.

Preferences live in `.actionboard/preferences.json` in the project root:

```json
{ "graphify": "enabled", "terse_output": "declined" }
```

Values are `enabled` or `declined`. A missing key means the user has not been asked yet.

## 1. Context7 MCP (mandatory)

Check that the Context7 MCP tools are available to you (`resolve-library-id` and `query-docs`;
the exact tool name carries a prefix that depends on the CLI). Call `resolve-library-id` once
with any well-known library to prove the server answers.

- **Available:** continue.
- **Missing or failing:** STOP the mission. Tell the user, in full sentences, that Context7 is
  required so agents can verify current library, MCP, and plugin versions, and how to fix it:
  re-run `python scripts/install.py --target <cli> ...` from the ActionBoard repository, which
  configures the hosted server `https://mcp.context7.com/mcp`, then restart the CLI. An optional
  `CONTEXT7_API_KEY` raises rate limits. Do not continue without it.

## 2. Graphify (ask before installing)

Goal: agents read a lightweight code graph instead of raw files.

1. `./graphify-out/graph.json` exists → run `graphify update .` (offline, no LLM, only changed
   files) if `graphify` is on PATH, then continue.
2. `graphify` is on PATH but there is no graph → build it offline (step 5).
3. `graphify` is not on PATH and preferences say `"graphify": "declined"` → skip; recon falls
   back to reading files.
4. `graphify` is not on PATH and the user has not been asked → show this note, then ask:

   > **Graphify** indexes your code into a lightweight graph map. Agents then read that map
   > instead of raw files, which saves input tokens and significantly reduces API cost. It is an
   > open-source Python package (`graphifyy`, Apache-2.0, no telemetry) and builds the code graph
   > offline without any API key.
   >
   > Install Graphify (`graphifyy` 0.9.95) now? **yes / no**

   Record the answer in preferences. On **yes**, install with the first tool that exists:

   ```sh
   uv tool install "graphifyy==0.9.95"
   pipx install "graphifyy==0.9.95"
   python -m pip install --user "graphifyy==0.9.95"     # Windows: py -m pip ...
   ```

   Before pinning, check the current release with Context7 or `https://pypi.org/pypi/graphifyy/json`
   and tell the user if a newer version exists; install the version the user agrees to.
5. Build the graph offline (zero tokens, no API key):

   ```sh
   graphify extract . --code-only
   graphify cluster-only . --no-label --no-viz
   ```

   Confirm `graphify-out/GRAPH_REPORT.md` exists. Suggest adding `graphify-out/` to
   `.gitignore`; do not edit `.gitignore` without asking.

Never run `graphify install`, `graphify <cli> install`, or `graphify hook install`: they change
global CLI configuration and are out of scope for a mission.

## 3. Terse output (ask before enabling)

If preferences have no `terse_output` key, show this note, then ask:

> **Terse output** (rules derived from Caveman, bundled with ActionBoard, nothing to download)
> optimizes and cuts down output tokens to reduce generation cost. It applies only to background
> agent chatter. Mission plans, mission reports, source code, commit messages, and security
> reviews always stay in full, standard prose.
>
> Enable terse output for this project? **yes / no**

Record the answer. When `enabled`, add the line `Terse output: on` to every assignment you
dispatch, and follow the `terse-output` skill for your own chatter.

## 4. Preflight report

Write the preferences file, then report in full prose:

| Check | Result | Detail |
|---|---|---|
| Context7 MCP | ready / missing | tool that answered |
| Graphify | graph ready / declined / install failed | version, node count from GRAPH_REPORT.md |
| Terse output | on / off | |

End with `Files created/changed:` listing `.actionboard/preferences.json`, `graphify-out/` if it
was built, or `none`.
