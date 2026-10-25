// Runs the built OpenCode guard plugin outside OpenCode. Node 23.6+ strips the
// TypeScript annotations natively:  node --test tests/opencode/
import assert from "node:assert/strict"
import { mkdtempSync, readFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import test from "node:test"
import { fileURLToPath, pathToFileURL } from "node:url"

const root = join(fileURLToPath(import.meta.url), "..", "..", "..")
const { ActionBoardGuard } = await import(pathToFileURL(join(root, "dist", "opencode", "plugins", "actionboard-guard.ts")).href)

const dir = mkdtempSync(join(tmpdir(), "af-opencode-"))
const hooks = await ActionBoardGuard({ directory: dir })
const before = (command, tool = "bash") => hooks["tool.execute.before"]({ tool }, { args: { command } })

test("allows unrelated and read-only commands", async () => {
  await before("ls -la")
  await before("openshell sandbox list")
  await before("openshell sandbox delete --all", "read")
})

test("denies blast-radius commands", async () => {
  await assert.rejects(before("openshell sandbox delete --all"), /cross-workspace/)
  await assert.rejects(before('openshell sandbox delete --all-work"spaces"'), /cross-workspace/)
  await assert.rejects(before("openshell sandbox create --env GITHUB_TOKEN=x"), /credential/)
})

test("asks pass to permission.bash only for plain commands", async () => {
  await before("openshell workspace delete team-a")
  await before("openshell policy set --global -f p.yaml")
  await assert.rejects(before('bash -c "openshell workspace delete team-a"'), /cannot ask/)
  await assert.rejects(before("echo $(openshell workspace delete a)"), /cannot ask/)
  await assert.rejects(before("openshell policy --global set"), /cannot ask/)
})

test("quote-split names do not skip the guard", async () => {
  await assert.rejects(before('"ope"nshell sandbox delete --all-workspaces'), /ActionBoard guard/)
  await assert.rejects(before("op''enshell sandbox delete --all-workspaces"), /ActionBoard guard/)
})

test("audits mutations after execution", async () => {
  await hooks["tool.execute.after"]({ tool: "bash", sessionID: "s9", args: { command: "openshell policy set -f p.yaml" } })
  const log = readFileSync(join(dir, ".openshell-audit.log"), "utf8")
  assert.match(log, /\ts9\tpolicy set\topenshell policy set -f p.yaml/)
})
