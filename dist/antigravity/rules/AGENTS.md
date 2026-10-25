# ActionBoard V5 Agent Formation

Run `/start-mission <objective>` to plan a mission: this session acts as Black Agent,
dispatches `green-agent` for recon, drafts the Mission Brief, Agent Assignments (with file
ownership), Skills Gap and Risk Register, then STOPS for go/no-go. After "go" it dispatches
`red-agent`, `blue-agent` and `yellow-agent` with `invoke_subagent`.

- Only dispatch the ActionBoard agents when a mission is running.
- Specialists never dispatch other agents and never commit.
- `openshell` commands are checked by the ActionBoard PreToolUse hook.
