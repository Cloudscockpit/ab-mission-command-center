// Runs the built OpenCode guard plugins outside OpenCode. Node 23.6+ strips the
// TypeScript annotations natively:  node --test tests/opencode/plugin.test.mjs
import assert from "node:assert/strict"
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"
import { fileURLToPath, pathToFileURL } from "node:url"

const root = join(fileURLToPath(import.meta.url), "..", "..", "..")
const dist = join(root, "dist", "opencode")
const load = (p) => import(pathToFileURL(p).href)

// ---------------------------------------------------------------- OpenCode 2.x

const v2 = (await load(join(dist, "plugins", "actionboard-guard.ts"))).default
const dir2 = mkdtempSync(join(tmpdir(), "af-opencode2-"))
const hooks = {}
await v2.setup({
  directory: dir2,
  permission: { hook: async (name, cb) => (hooks["permission." + name] = cb) },
  tool: { hook: async (name, cb) => (hooks["tool." + name] = cb) },
})
const evaluate = (resources, effect = "allow") => {
  const event = { sessionID: "s1", action: "shell", resources, effect }
  hooks["permission.evaluate"](event)
  return event
}

test("2.x: default export has id and setup", () => {
  assert.equal(v2.id, "actionboard-guard")
  assert.equal(typeof v2.setup, "function")
  assert.ok(hooks["permission.evaluate"] && hooks["tool.execute.after"])
})

test("2.x: allows unrelated and read-only commands", () => {
  assert.equal(evaluate(["ls -la"]).effect, "allow")
  assert.equal(evaluate(["openshell sandbox list"]).effect, "allow")
  const other = { sessionID: "s", action: "read", resources: ["openshell sandbox delete --all"], effect: "allow" }
  hooks["permission.evaluate"](other)
  assert.equal(other.effect, "allow")
})

test("2.x: denies blast-radius commands, most severe resource wins", () => {
  const e = evaluate(["openshell workspace delete a", "openshell sandbox delete --all-workspaces"])
  assert.equal(e.effect, "deny")
  assert.match(e.message, /cross-workspace/)
  assert.equal(evaluate(['"ope"nshell sandbox delete --all-workspaces']).effect, "deny")
})

test("2.x: asks natively, and never weakens a configured ask", () => {
  const e = evaluate(['bash -c "openshell workspace delete team-a"'])
  assert.equal(e.effect, "ask")
  assert.match(e.message, /workspace/)
  assert.equal(evaluate(["ls"], "ask").effect, "ask")
})

test("2.x: audits shell mutations after execution", async () => {
  await hooks["tool.execute.after"]({ tool: "shell", sessionID: "s9", input: { command: "openshell policy set -f p.yaml" }, status: "completed" })
  const log = readFileSync(join(dir2, ".openshell-audit.log"), "utf8")
  assert.match(log, /\ts9\tpolicy set\topenshell policy set -f p.yaml/)
})

// ---------------------------------------------------------------- OpenCode 1.x (legacy)

// Installed layout: the installer puts the legacy file at plugins/actionboard-guard.ts.
const inst = mkdtempSync(join(tmpdir(), "af-opencode1-"))
cpSync(dist, inst, { recursive: true })
writeFileSync(join(inst, "plugins", "actionboard-guard.ts"),
  readFileSync(join(dist, "actionboard", "legacy", "actionboard-guard.v1.ts")))
rmSync(join(inst, "actionboard", "legacy"), { recursive: true })
const { ActionBoardGuard } = await load(join(inst, "plugins", "actionboard-guard.ts"))
const dir1 = mkdtempSync(join(tmpdir(), "af-opencode1-run-"))
const v1 = await ActionBoardGuard({ directory: dir1 })
const before = (command, tool = "bash") => v1["tool.execute.before"]({ tool }, { args: { command } })

test("1.x: allows unrelated and read-only commands", async () => {
  await before("ls -la")
  await before("openshell sandbox list")
  await before("openshell sandbox delete --all", "read")
})

test("1.x: denies blast-radius commands", async () => {
  await assert.rejects(before("openshell sandbox delete --all"), /cross-workspace/)
  await assert.rejects(before("openshell sandbox create --env GITHUB_TOKEN=x"), /credential/)
})

test("1.x: asks pass to permission.bash only for plain commands", async () => {
  await before("openshell workspace delete team-a")
  await assert.rejects(before('bash -c "openshell workspace delete team-a"'), /cannot ask/)
  await assert.rejects(before("openshell policy --global set"), /cannot ask/)
  await assert.rejects(before('"ope"nshell sandbox delete --all-workspaces'), /ActionBoard guard/)
})

test("1.x: audits mutations after execution", async () => {
  await v1["tool.execute.after"]({ tool: "bash", sessionID: "s8", args: { command: "openshell policy set -f p.yaml" } })
  assert.match(readFileSync(join(dir1, ".openshell-audit.log"), "utf8"), /\ts8\tpolicy set\t/)
})
