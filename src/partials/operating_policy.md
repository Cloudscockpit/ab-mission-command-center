## Operating policy (cost and accuracy)

1. **Recon through the graph.** When `./graphify-out/` exists, read `graphify-out/GRAPH_REPORT.md`
   first and use `graphify query`, `graphify path`, and `graphify explain` before opening source
   files. Then read only the files and line ranges the graph points to.
2. **Verify versions with Context7.** Before you choose, pin, or recommend a version of any
   library, framework, MCP server, plugin, or CLI, look it up with the Context7 MCP tools
   (`resolve-library-id`, then `query-docs`). Never rely on memory for versions or APIs.
   If the Context7 tools are unavailable, say so in your report instead of guessing.
3. **Terse chatter only when enabled.** When your assignment says `Terse output: on`, follow the
   `terse-output` skill for progress messages and status lines. Otherwise write normally.
4. **Never compress these.** Mission briefs, mission plans, mission reports, source code,
   code comments, commit messages, security reviews and findings, and the file change summary are
   always written in full, clear, standard prose, with every table, field, and markdown structure
   intact. Graph summaries never replace content those documents require.
5. **File change summary.** End every report with a `Files created/changed:` list naming every
   path you created, modified, or deleted, or `none`.
