#!/usr/bin/env python3
"""Translate one CLI's native hook payload to the neutral guard/audit contract.

    python cli_hook.py --cli <claude|codex|antigravity> --event <pre|post>

Reads the native JSON payload on stdin, writes the native response on stdout,
and always exits 0: a decision is always expressed in JSON so a crashing hook
is never mistaken for an allow.

Per-CLI "ask" handling:
  claude       native ask.
  antigravity  native ask.
  codex        hooks cannot ask. An ask is passed through only when the command
               is one literal openshell call whose argv starts with the exact
               prefix of a "prompt" rule in .codex/rules/actionboard.rules;
               otherwise it is denied.
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CLIS = ("antigravity", "claude", "codex")

# Ask rules each CLI's static rules can express, with the literal argv prefix
# the rule matches. Keep in sync with adapters/codex/actionboard.rules.
STATIC_ASK = {
    "codex": {
        "global-policy": ["openshell", "policy", "set"],
        "workspace-delete": ["openshell", "workspace", "delete"],
    },
}

SHELL_TOOLS = {
    "claude": {"Bash", "PowerShell"},
    "codex": {"Bash", "shell", "exec_command", "local_shell"},
    "antigravity": {"run_command"},
}

GUARD_FAILED = ("The OpenShell guard failed while evaluating this command, which "
                "mentions openshell. Review it manually before allowing.")


def extract(cli, payload):
    """Return (tool, command, session, cwd) from a native payload."""
    if cli == "antigravity":
        call = payload.get("toolCall") or {}
        args = call.get("args") or {}
        roots = payload.get("workspacePaths") or []
        return (call.get("name") or "", args.get("CommandLine") or "",
                payload.get("conversationId") or "",
                args.get("Cwd") or (roots[0] if roots else ""))
    tool_input = payload.get("tool_input") or {}
    command = tool_input.get("command") or tool_input.get("cmd") or ""
    if isinstance(command, list):  # some shells pass argv
        command = " ".join(str(c) for c in command)
    return (payload.get("tool_name") or "", command,
            payload.get("session_id") or "", payload.get("cwd") or "")


def respond_pre(cli, decision, reason):
    if cli == "antigravity":
        return {"decision": decision, "reason": reason} if decision != "allow" else {"decision": "allow"}
    if decision == "allow":
        return None
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": decision,
                                   "permissionDecisionReason": reason}}


def downgrade(cli, result, command, openshell):
    """Map an "ask" onto CLIs whose hooks cannot ask."""
    decision, reason = result["decision"], result["reason"]
    if decision != "ask" or cli not in STATIC_ASK:
        return decision, reason
    prefix = STATIC_ASK[cli].get(result.get("rule"))
    argv = openshell.plain_argv(command)
    if prefix and argv and argv[:len(prefix)] == prefix:
        return "allow", ""  # the static prompt rule asks the user
    return "deny", (reason + " This CLI cannot ask from a hook, so the command was "
                    "blocked. Run it as one plain `openshell ...` command so the "
                    "permission prompt can catch it, or run it yourself.")


def pre(cli, data):
    sys.path.insert(0, os.path.join(HERE, "core"))
    import guard
    import openshell
    try:
        payload = json.loads(data)
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")
        tool, command, _, _ = extract(cli, payload)
        if not isinstance(command, str):
            raise ValueError("command must be a string")
    except Exception:
        if openshell.mentions_openshell(data):
            result = {"decision": "ask", "reason": openshell.PARSE_ERROR_REASON, "rule": "parse-error"}
            return respond_pre(cli, *downgrade(cli, result, "", openshell))
        return respond_pre(cli, "allow", "")
    if tool not in SHELL_TOOLS[cli]:
        return respond_pre(cli, "allow", "")
    result = guard.decide({"tool": "bash", "command": command})
    return respond_pre(cli, *downgrade(cli, result, command, openshell))


def post(cli, data):
    sys.path.insert(0, os.path.join(HERE, "core"))
    import audit
    try:
        payload = json.loads(data)
        tool, command, session, cwd = extract(cli, payload)
        if tool in SHELL_TOOLS[cli]:
            audit.record({"command": command, "session": session, "cwd": cwd or os.getcwd()})
    except Exception:
        pass
    return {} if cli == "antigravity" else None


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    cli = argv[argv.index("--cli") + 1] if "--cli" in argv[:-1] else ""
    event = argv[argv.index("--event") + 1] if "--event" in argv[:-1] else ""
    out = None
    try:
        data = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    except Exception:
        data = "openshell"  # unreadable input: assume the worst
    try:
        if cli not in CLIS or event not in ("pre", "post"):
            raise ValueError("usage: cli_hook.py --cli <%s> --event <pre|post>" % "|".join(CLIS))
        out = (pre if event == "pre" else post)(cli, data)
    except Exception:
        # Fail closed: any crash on a pre-tool payload that could be openshell asks
        # (or denies, where the CLI cannot ask). Checked without the core modules,
        # since a failed import may be why we are here.
        if event == "pre" and "openshell" in data.lower().replace('"', "").replace("'", ""):
            decision = "deny" if cli in STATIC_ASK else "ask"
            out = respond_pre(cli if cli in CLIS else "claude", decision, GUARD_FAILED)
        elif event == "post" and cli == "antigravity":
            out = {}
    if out is not None:
        sys.stdout.write(json.dumps(out) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
