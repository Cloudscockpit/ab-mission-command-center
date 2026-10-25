---
description: Build the sandbox harness for a ActionBoard V5 mission — one isolated environment per assigned Agent, sized and policed by role, created only after go/no-go. Use when forming ActionBoard V5 for real execution.
agent: sandbox-warden
subtask: true
---

Load the `mission-harness` skill with the `skill` tool and follow its instructions.

Request: $ARGUMENTS

If the request is empty and the skill needs one, ask the user before acting.
