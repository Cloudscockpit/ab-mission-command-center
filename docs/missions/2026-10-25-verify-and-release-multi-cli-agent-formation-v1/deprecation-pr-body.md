## Summary

This repository's Agent Formation (v0.6.1, Claude Code and Cowork only) has a successor:
[Cloudscockpit/ab-mission-command-center](https://github.com/Cloudscockpit/ab-mission-command-center).
Version 1.0.0 there builds the same agents, skills, and OpenShell guard for **Claude Code,
OpenCode, Codex CLI and Antigravity CLI** from one neutral source.

This PR only adds a banner to the top of `README.md` pointing readers there, with the two
Claude Code commands to switch marketplaces. No code, skill, agent, hook, or manifest changes;
v0.6.1 stays installable exactly as it is.

## What the successor adds

- The same `/start-mission` flow on four CLIs, verified live with two full missions on each
  (Claude Code 2.1.310, OpenCode 2.1.4, Codex CLI 0.164.0, Antigravity CLI 1.4.7).
- A Python OpenShell guard shared by every CLI, with 16 parser bypasses from a security review
  closed, and hooks that fail closed.
- Mandatory Context7 MCP, an optional offline code graph (Graphify), and optional terse output
  for agent chatter, each asked before it is enabled.
- A Maturity & Progress Summary in every mission report, scored with the formation gate's rules.

## Test plan

- [ ] The banner renders as a GitHub "Important" callout on the repository page.
- [ ] The link opens `Cloudscockpit/ab-mission-command-center` for a signed-out reader.
- [ ] `git diff main` touches `README.md` only.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
