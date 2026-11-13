---
description: Log the user in to ActionBoard from the CLI and choose the Pod and Board that missions are submitted to. Use when the user runs "ab-login", asks to "log in to ActionBoard", "connect my ActionBoard account", "switch pod", or "switch board", and whenever a mission submit or fetch reports that the user is not logged in or has no Pod/Board selected.
---

Load the `ab-login` skill with the `skill` tool and follow its instructions.

Request: $ARGUMENTS

If the request is empty and the skill needs one, ask the user before acting.
