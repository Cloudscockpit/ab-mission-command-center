// ActionBoard OpenShell guard + audit for OpenCode.
//
// tool.execute.before runs the neutral guard (actionboard/hooks/core/guard.py)
// on every bash call (no text pre-filter: "ope"nshell must not slip past). A
// plugin hook cannot "ask" in OpenCode, so:
//   deny -> throw (the message goes back to the model)
//   ask  -> pass through ONLY when the command is one literal openshell call
//           that the agents' permission.bash ask pattern for that rule really
//           matches (OpenCode then prompts the user); otherwise throw.
// Fails CLOSED: if Python is unavailable or the guard crashes, any command
// that could mention openshell is blocked.
//
// tool.execute.after appends state-changing openshell calls to
// .openshell-audit.log via audit.py and never throws.

import { spawnSync } from "node:child_process"
import { existsSync, readFileSync } from "node:fs"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "actionboard")
const CORE = join(ROOT, "hooks", "core")
// Mirrors OPENSHELL_BASH in adapters/opencode/adapter.py (glob patterns).
const STATIC_ASK: Record<string, (cmd: string) => boolean> = {
  "global-policy": (cmd) => cmd.startsWith("openshell policy set ") && cmd.includes("--global"),
  "workspace-delete": (cmd) => cmd.startsWith("openshell workspace delete"),
  "full-endpoint": (cmd) => cmd.startsWith("openshell ") && cmd.includes(":full"),
}

const mentions = (text: string) => text.replace(/["'\\^`]/g, "").toLowerCase().includes("openshell")

type Verdict = { decision: string; reason: string; rule: string; plain: boolean }

let python: string[] | null | undefined

function findPython(): string[] | null {
  if (python !== undefined) return python
  const candidates: string[][] = []
  try {
    const configured = JSON.parse(readFileSync(join(ROOT, "config.json"), "utf8")).python
    if (configured && !configured.startsWith("__") && existsSync(configured)) candidates.push([configured])
  } catch {}
  candidates.push(["python3"], ["python"], ["py", "-3"])
  python = null
  for (const c of candidates) {
    const probe = spawnSync(c[0], [...c.slice(1), "-c", "import sys; sys.exit(sys.version_info < (3, 9))"], {
      stdio: "ignore",
    })
    if (probe.status === 0) {
      python = c
      break
    }
  }
  return python
}

function run(script: string, payload: object, cwd: string): string | null {
  const py = findPython()
  if (!py) return null
  const res = spawnSync(py[0], [...py.slice(1), join(CORE, script)], {
    input: JSON.stringify(payload),
    encoding: "utf8",
    cwd,
    timeout: 15000,
  })
  return res.status === 0 ? res.stdout : null
}

export const ActionBoardGuard = async ({ directory }: { directory: string }) => {
  return {
    "tool.execute.before": async (input: { tool: string }, output: { args: any }) => {
      if (input.tool !== "bash") return
      const command: string = String(output.args?.command ?? "")
      const raw = run("guard.py", { tool: "bash", command }, directory)
      let verdict: Verdict
      try {
        verdict = JSON.parse(raw ?? "")
      } catch {
        if (!mentions(command)) return
        throw new Error(
          "ActionBoard guard could not run (Python 3.9+ unavailable or guard failed) and this " +
            "command mentions openshell. Blocked; review it and run it yourself if intended.",
        )
      }
      if (verdict.decision === "deny") throw new Error(`ActionBoard guard: ${verdict.reason}`)
      const staticAsk = STATIC_ASK[verdict.rule]
      if (verdict.decision === "ask" && !(verdict.plain && staticAsk && staticAsk(command.trim()))) {
        throw new Error(
          `ActionBoard guard: ${verdict.reason} OpenCode cannot ask from a plugin, so the command ` +
            "was blocked. Run it as one plain `openshell ...` command so the permission prompt " +
            "can catch it, or run it yourself.",
        )
      }
    },
    "tool.execute.after": async (input: { tool: string; sessionID: string; args?: any }) => {
      if (input.tool !== "bash") return
      const command: string = String(input.args?.command ?? "")
      if (!mentions(command)) return
      try {
        run("audit.py", { tool: "bash", command, session: input.sessionID, cwd: directory }, directory)
      } catch {}
    },
  }
}
