#!/usr/bin/env python3
"""Pre-tool guard: decide whether a shell command may run.

Neutral contract (every CLI adapter translates to and from this):

    stdin : {"tool": "bash", "command": "..."}
    stdout: {"decision": "allow|ask|deny", "reason": "...", "rule": "...",
             "plain": true|false}

`rule` names the check that fired: cross-workspace-delete, global-policy,
workspace-delete, credential-env, full-endpoint, indirect, parse-error.

`plain` is true when the command is one literal `openshell ...` call, so a CLI
without an "ask" hook result can safely hand an ask to its static permission
patterns. Fails CLOSED: an unreadable payload that mentions openshell is "ask".
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import openshell  # noqa: E402


def decide(payload):
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    command = payload.get("command") or ""
    if not isinstance(command, str):
        raise ValueError("command must be a string")
    decision, reason, rule = openshell.evaluate(command)
    return {"decision": decision, "reason": reason, "rule": rule,
            "plain": openshell.is_plain_invocation(command)}


def main():
    data = sys.stdin.read()
    try:
        result = decide(json.loads(data))
    except Exception:
        if openshell.mentions_openshell(data):
            result = {"decision": openshell.ASK, "reason": openshell.PARSE_ERROR_REASON,
                      "rule": "parse-error", "plain": False}
        else:
            result = {"decision": openshell.ALLOW, "reason": "", "rule": "", "plain": False}
    sys.stdout.write(json.dumps(result) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
