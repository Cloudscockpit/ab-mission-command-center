// ActionBoard OpenShell guard + audit for OpenCode 2.x.
//
// permission "evaluate" hook: runs after the agents' configured permission rules
// and before a shell command runs or a prompt is shown. OpenCode passes each
// command the shell scanner found as a resource; the neutral guard
// (actionboard/hooks/core/guard.py) checks every one and the most severe wins:
//   deny -> effect "deny" with the reason
//   ask  -> effect "ask" with the reason (OpenCode 2.x prompts natively)
// An explicit configured deny is final and never reaches this hook.
// Fails CLOSED: if Python is unavailable or the guard crashes, a command that
// mentions openshell is denied.
//
// tool "execute.after" hook: appends state-changing openshell calls to
// .openshell-audit.log via audit.py and never throws.
//
// OpenCode 1.x loads named exports instead; scripts/install.py installs
// actionboard/legacy/actionboard-guard.v1.ts there.

import { audit, evaluate, GUARD_UNAVAILABLE, mentionsOpenshell } from "../actionboard/guard-client.ts"

type Evaluation = {
  readonly sessionID: string
  readonly action: string
  readonly resources: readonly string[]
  effect: "allow" | "ask" | "deny"
  message?: string
}

const RANK = { allow: 0, ask: 1, deny: 2 } as const

export function decide(resources: readonly string[], cwd: string): { effect: "allow" | "ask" | "deny"; message: string } {
  let best: { effect: "allow" | "ask" | "deny"; message: string } = { effect: "allow", message: "" }
  for (const command of resources) {
    const verdict = evaluate(command, cwd)
    const found = verdict
      ? { effect: verdict.decision, message: verdict.reason ? `ActionBoard guard: ${verdict.reason}` : "" }
      : mentionsOpenshell(command)
        ? { effect: "deny" as const, message: GUARD_UNAVAILABLE }
        : { effect: "allow" as const, message: "" }
    if (RANK[found.effect] > RANK[best.effect]) best = found
  }
  return best
}

export default {
  id: "actionboard-guard",
  async setup(ctx: any) {
    const cwd: string = ctx.directory ?? ctx.project?.directory ?? process.cwd()
    await ctx.permission.hook("evaluate", (event: Evaluation) => {
      if (event.action !== "shell") return
      const verdict = decide(event.resources, cwd)
      if (RANK[verdict.effect] > RANK[event.effect]) {
        event.effect = verdict.effect
        event.message = verdict.message
      }
    })
    await ctx.tool.hook("execute.after", (event: any) => {
      if (event.tool !== "shell") return
      const input = event.input ?? {}
      audit(String(input.command ?? input.cmd ?? ""), String(event.sessionID ?? "nosession"), cwd)
    })
  },
}
