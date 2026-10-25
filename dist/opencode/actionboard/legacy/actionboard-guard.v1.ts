// ActionBoard OpenShell guard + audit for OpenCode 1.x (legacy).
// scripts/install.py installs this as plugins/actionboard-guard.ts only when it
// detects OpenCode 1.x; OpenCode 2.x gets the permission-hook plugin instead.
//
// tool.execute.before runs the neutral guard on every bash call (no text
// pre-filter: "ope"nshell must not slip past). A 1.x plugin hook cannot "ask", so:
//   deny -> throw (the message goes back to the model)
//   ask  -> pass through ONLY when the command is one literal openshell call
//           that the agents' permission.bash ask pattern for that rule really
//           matches (OpenCode then prompts the user); otherwise throw.
// Fails CLOSED: if Python is unavailable or the guard crashes, any command
// that could mention openshell is blocked.

import { audit, evaluate, GUARD_UNAVAILABLE, mentionsOpenshell } from "../actionboard/guard-client.ts"

// Mirrors OPENSHELL_BASH in adapters/opencode/adapter.py (glob patterns).
const STATIC_ASK: Record<string, (cmd: string) => boolean> = {
  "global-policy": (cmd) => cmd.startsWith("openshell policy set ") && cmd.includes("--global"),
  "workspace-delete": (cmd) => cmd.startsWith("openshell workspace delete"),
  "full-endpoint": (cmd) => cmd.startsWith("openshell ") && cmd.includes(":full"),
}

export const ActionBoardGuard = async ({ directory }: { directory: string }) => {
  return {
    "tool.execute.before": async (input: { tool: string }, output: { args: any }) => {
      if (input.tool !== "bash") return
      const command: string = String(output.args?.command ?? "")
      const verdict = evaluate(command, directory)
      if (!verdict) {
        if (!mentionsOpenshell(command)) return
        throw new Error(GUARD_UNAVAILABLE)
      }
      if (verdict.decision === "deny") throw new Error(`ActionBoard guard: ${verdict.reason}`)
      const staticAsk = STATIC_ASK[verdict.rule]
      if (verdict.decision === "ask" && !(verdict.plain && staticAsk && staticAsk(command.trim()))) {
        throw new Error(
          `ActionBoard guard: ${verdict.reason} OpenCode 1.x cannot ask from a plugin, so the command ` +
            "was blocked. Run it as one plain `openshell ...` command so the permission prompt " +
            "can catch it, or run it yourself.",
        )
      }
    },
    "tool.execute.after": async (input: { tool: string; sessionID: string; args?: any }) => {
      if (input.tool !== "bash") return
      audit(String(input.args?.command ?? ""), input.sessionID, directory)
    },
  }
}
