// Shared by the OpenCode 2.x plugin (plugins/actionboard-guard.ts) and the
// OpenCode 1.x legacy plugin. Runs the neutral Python hook core
// (actionboard/hooks/core/{guard,audit}.py) and never uses a shell.

import { spawnSync } from "node:child_process"
import { existsSync, readFileSync } from "node:fs"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"

const ROOT = dirname(fileURLToPath(import.meta.url))
const CORE = join(ROOT, "hooks", "core")

export type Verdict = { decision: "allow" | "ask" | "deny"; reason: string; rule: string; plain: boolean }

export const GUARD_UNAVAILABLE =
  "ActionBoard guard could not run (Python 3.9+ unavailable or guard failed) and this command " +
  "mentions openshell. Review it and run it yourself if intended."

/** Quote-insensitive: op''enshell and "ope"nshell both count. */
export const mentionsOpenshell = (text: string) =>
  text.replace(/["'\\^`]/g, "").toLowerCase().includes("openshell")

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

/** Guard verdict for one command, or null when the guard could not run. */
export function evaluate(command: string, cwd: string): Verdict | null {
  try {
    return JSON.parse(run("guard.py", { tool: "bash", command }, cwd) ?? "")
  } catch {
    return null
  }
}

/** Append state-changing openshell calls to .openshell-audit.log. Never throws. */
export function audit(command: string, session: string, cwd: string): void {
  if (!mentionsOpenshell(command)) return
  try {
    run("audit.py", { tool: "bash", command, session, cwd }, cwd)
  } catch {}
}
