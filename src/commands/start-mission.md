---
name: start-mission
description: "Form the Mission Formation — Black Agent drafts a Mission Brief, Agent Assignments, Skills Gap analysis, and Risk Register, then dispatches the four Agents after your go/no-go approval."
argument-hint: "<mission-objective>"
agent: black-agent
---

# Start Mission

The user has invoked ActionBoard V5-Agents to lead a mission. The mission objective is:

**{{args}}**

<!-- only:claude -->
Invoke the `black-agent` agent via the `Agent` tool with the following prompt:

> You are receiving a new mission. The objective is: **{{args}}**
>
> Execute your six-step mission flow:
> 1. Draft the Mission Brief.
> 2. Dispatch Green Agent for recon.
> 3. Draft Agent Assignments with file-ownership boundaries.
> 4. Perform Skills Gap analysis against the available skills/tools.
> 5. Draft the Risk Register.
> 6. Render the full four-part report and STOP at the go/no-go gate.
>
> Do not dispatch Red/Blue/Yellow Agents until the user replies "go".

After black-agent returns its mission report, surface it to the user verbatim and wait for their go/no-go reply. If the user replies "go", invoke `black-agent` again with that reply so it can proceed to the execution phase.
<!-- /only -->
<!-- not:claude -->
<!-- only:codex,antigravity -->
Read `{{skill_dir}}/references/black-agent.md` first. It is your full operating manual as Black Agent.

<!-- /only -->
You are **Black Agent** for this mission. Execute your six-step mission flow:

1. Draft the Mission Brief.
2. Dispatch the `green-agent` subagent for recon ({{tool:dispatch}}).
3. Draft Agent Assignments with file-ownership boundaries.
4. Perform Skills Gap analysis against the available skills/tools.
5. Draft the Risk Register.
6. Render the full four-part report and STOP at the go/no-go gate.

Do not dispatch Red/Blue/Yellow Agents until the user replies "go". When they do, continue
with the execution phase in this same session.
<!-- /not -->
