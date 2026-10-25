#!/usr/bin/env python3
"""Post-tool audit: append every OpenShell state mutation to a local log.

Neutral contract:

    stdin : {"tool": "bash", "command": "...", "session": "...", "cwd": "..."}
    stdout: nothing

The log is $OPENSHELL_AUDIT_LOG, else <cwd>/.openshell-audit.log. Each line is
tab-separated: UTC timestamp, session id, verb, argv. Coverage is deliberately
wider than the guard's: the guard only stops what is dangerous, the log records
everything that CHANGES state, including actions the guard merely asks about.

Never blocks and never fails the tool call: always exits 0.

The log lives in the agent's working tree, so it is an advisory trail, not a
tamper-evident one: an agent can edit it with commands that never mention
openshell. Point OPENSHELL_AUDIT_LOG outside the workspace when that matters.
"""

import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import openshell  # noqa: E402


def log_path(payload):
    explicit = os.environ.get("OPENSHELL_AUDIT_LOG")
    if explicit:
        return explicit
    return os.path.join(payload.get("cwd") or os.getcwd(), ".openshell-audit.log")


def record(payload, now=None):
    command = payload.get("command") or ""
    if not isinstance(command, str):
        return []
    entries = openshell.audit_entries(command)
    if not entries:
        return []
    ts = (now or datetime.datetime.now(datetime.timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    session = re.sub(r"[\t\r\n]", " ", str(payload.get("session") or "nosession"))
    lines = ["%s\t%s\t%s\t%s\n" % (ts, session, verb, argv) for verb, argv in entries]
    with open(log_path(payload), "a", encoding="utf-8") as fh:
        fh.writelines(lines)
    return lines


def main():
    data = sys.stdin.read()
    try:
        payload = json.loads(data)
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")
    except Exception:
        payload = None
    try:
        if payload is not None:
            record(payload)
        elif openshell.mentions_openshell(data):
            # Cannot parse; record the raw payload rather than silently dropping it.
            ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            with open(log_path({}), "a", encoding="utf-8") as fh:
                fh.write("%s\tnosession\tUNPARSED\t%s\n"
                         % (ts, data.replace("\t", " ").replace("\n", " ")))
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
