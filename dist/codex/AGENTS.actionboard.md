<!-- actionboard:begin -->
## ActionBoard V5 Agent Formation

Run `$start-mission <objective>` to plan a mission: this session acts as Black Agent,
spawns `green-agent` for recon, drafts the Mission Brief, Agent Assignments (with file
ownership), Skills Gap and Risk Register, then STOPS for go/no-go. After "go" it spawns
`red-agent`, `blue-agent` and `yellow-agent` (custom agents in `.codex/agents/`).

- Only spawn the ActionBoard agents when a mission is running.
- Specialists never spawn other agents and never commit.
- `openshell` commands are checked by the ActionBoard hook (`.codex/hooks.json`) and
  `.codex/rules/actionboard.rules`.
<!-- actionboard:end -->
