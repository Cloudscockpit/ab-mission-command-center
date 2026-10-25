// Zero-clone npx installer, offline:  node --test tests/installer/install.test.mjs
// Needs a real Python 3.9+ for the end-to-end cases (they are skipped without one).
import assert from "node:assert/strict"
import { spawnSync } from "node:child_process"
import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs"
import { createRequire } from "node:module"
import { tmpdir } from "node:os"
import { join, resolve } from "node:path"
import test from "node:test"
import { fileURLToPath } from "node:url"

const root = join(fileURLToPath(import.meta.url), "..", "..", "..")
const script = join(root, "packages", "installer", "bin", "install.js")
const inst = createRequire(import.meta.url)(script)
const PKG = createRequire(import.meta.url)(join(root, "packages", "installer", "package.json"))
const py = inst.resolvePython()
const needPy = py ? false : "no Python 3.9+ on this machine"

const usage = (fn, re) => assert.throws(fn, (e) => e.constructor.name === "UsageError" && re.test(e.message))

// ---------------------------------------------------------------- parseArgs

test("parseArgs accepts every installable target", () => {
  for (const t of ["codex", "antigravity", "opencode"]) {
    const o = inst.parseArgs(["--target", t], "/work")
    assert.equal(o.target, t)
    assert.equal(o.global, false)
  }
  assert.deepEqual(inst.TARGETS, ["codex", "antigravity", "opencode"])
})

test("parseArgs rejects claude, all, unknown and missing targets", () => {
  usage(() => inst.parseArgs(["--target", "claude"], "/w"), /plugin marketplace add Cloudscockpit\/ab-mission-command-center/)
  usage(() => inst.parseArgs(["--target", "all"], "/w"), /invalid --target "all"/)
  usage(() => inst.parseArgs(["--target", "vim"], "/w"), /invalid --target/)
  usage(() => inst.parseArgs([], "/w"), /--target is required/)
  usage(() => inst.parseArgs(["--target"], "/w"), /--target requires a value/)
  usage(() => inst.parseArgs(["--target", "--global"], "/w"), /--target requires a value/)
})

test("parseArgs rejects --global with --project and unknown flags", () => {
  usage(() => inst.parseArgs(["--target", "codex", "--global", "--project", "x"], "/w"), /mutually exclusive/)
  usage(() => inst.parseArgs(["--target", "codex", "--project=x", "--global"], "/w"), /mutually exclusive/)
  usage(() => inst.parseArgs(["--target", "codex", "--cleanup"], "/w"), /unknown argument: --cleanup/)
  usage(() => inst.parseArgs(["--target", "codex", "stray"], "/w"), /unknown argument: stray/)
  usage(() => inst.parseArgs(["--target", "codex", "--config", "x"], "/w"), /unknown argument/)
})

test("parseArgs supports --flag=value and resolves --project against cwd", () => {
  const o = inst.parseArgs(["--target=opencode", "--project=sub/dir", "--with=graphify,terse", "--without=x", "--yes"], "/work")
  assert.equal(o.target, "opencode")
  assert.equal(o.projectAbs, resolve("/work", "sub/dir"))
  assert.equal(o.with, "graphify,terse")
  assert.equal(o.without, "x")
  assert.equal(o.yes, true)
  assert.equal(inst.parseArgs(["--target", "codex"], "/work").projectAbs, resolve("/work"))
  const abs = resolve("/somewhere/else")
  assert.equal(inst.parseArgs(["--target", "codex", "--project", abs], "/work").projectAbs, abs)
})

test("parseArgs help/version short-circuit validation", () => {
  assert.equal(inst.parseArgs(["--help"], "/w").help, true)
  assert.equal(inst.parseArgs(["-v"], "/w").version, true)
})

test("buildInstallArgs: project install passes an absolute --project", () => {
  const o = inst.parseArgs(["--target", "codex", "--project", "rel", "--uninstall", "--dry-run", "--yes", "--force",
    "--with", "graphify", "--without", "terse"], "/work")
  assert.deepEqual(inst.buildInstallArgs(o), ["--target", "codex", "--project", resolve("/work", "rel"),
    "--uninstall", "--dry-run", "--yes", "--force", "--with", "graphify", "--without", "terse"])
})

test("buildInstallArgs: global install has no --project and never forwards --cleanup", () => {
  const a = inst.buildInstallArgs(inst.parseArgs(["--target", "antigravity", "--global"], "/work"))
  assert.deepEqual(a, ["--target", "antigravity", "--global"])
  assert.ok(!a.includes("--cleanup"))
})

// ---------------------------------------------------------------- resolvePython

const ok = (exe, good = "True") => ({ status: 0, stdout: `${good}\n${exe}\n` })

test("resolvePython skips candidates that fail, are Store stubs, or are < 3.9", () => {
  const seen = []
  const spawn = (cmd, args) => {
    seen.push([cmd, args])
    if (cmd === "py") return { status: 9009, stdout: "" }                       // launcher missing / failing
    if (cmd === "python3") return { status: 0, stdout: "" }                     // Store stub: exits quietly, prints nothing
    if (cmd === "python") return ok("/opt/py38/bin/python", "False")            // too old
    throw new Error("unexpected " + cmd)
  }
  assert.equal(inst.resolvePython({}, spawn), null)
  assert.ok(seen.length >= 2)
  for (const [, args] of seen) assert.ok(args.includes("-I"), "probe must run isolated")
})

test("resolvePython returns the first working candidate and its real executable", () => {
  const spawn = (cmd) => {
    if (cmd === "python3") return { status: 0, stdout: "", error: undefined }
    if (cmd === "py" || cmd === "python") return ok("/real/python")
    return { status: 1, stdout: "" }
  }
  const r = inst.resolvePython({}, spawn)
  assert.equal(r.executable, "/real/python")
  assert.ok(["py", "python"].includes(r.cmd))
})

test("resolvePython prefers ACTIONBOARD_PYTHON, falls back when it is broken", () => {
  const calls = []
  const spawn = (cmd) => {
    calls.push(cmd)
    if (cmd === "/custom/python") return ok("/custom/python")
    return ok("/other")
  }
  assert.equal(inst.resolvePython({ ACTIONBOARD_PYTHON: "/custom/python" }, spawn).executable, "/custom/python")
  assert.equal(calls[0], "/custom/python")
  const broken = (cmd) => (cmd === "/custom/python" ? { status: 1, stdout: "" } : ok("/other"))
  assert.equal(inst.resolvePython({ ACTIONBOARD_PYTHON: "/custom/python" }, broken).executable, "/other")
})

const venvOut = (exe, venv) => ({ status: 0, stdout: `True\n${exe}\n${venv}\n` })

test("resolvePython skips virtualenv interpreters when a system Python exists", () => {
  const spawn = (cmd) => {
    if (cmd === "python3") return venvOut("/proj/.venv/bin/python", "True")
    return venvOut("/usr/bin/python", "False")
  }
  const r = inst.resolvePython({}, spawn)
  assert.equal(r.executable !== "/proj/.venv/bin/python", true)
  assert.ok(!r.warning)
})

test("resolvePython uses a venv Python only as a last resort, with a warning", () => {
  const spawn = (cmd) => (cmd === "python3" ? venvOut("/proj/.venv/bin/python", "True") : { status: 1, stdout: "" })
  const r = inst.resolvePython({}, spawn)
  assert.equal(r.executable, "/proj/.venv/bin/python")
  assert.match(r.warning, /virtualenv/)
})

test("resolvePython accepts a venv ACTIONBOARD_PYTHON explicitly, with a warning", () => {
  const spawn = (cmd) => (cmd === "/v/bin/python" ? venvOut("/v/bin/python", "True") : venvOut("/usr/bin/python", "False"))
  const r = inst.resolvePython({ ACTIONBOARD_PYTHON: "/v/bin/python" }, spawn)
  assert.equal(r.executable, "/v/bin/python")
  assert.match(r.warning, /virtualenv/)
})

test("resolvePython tolerates spawn throwing and spawn errors (ENOENT)", () => {
  const spawn = (cmd) => {
    if (cmd === "python3") throw new Error("boom")
    if (cmd === "python") return { error: new Error("ENOENT"), status: null, stdout: null }
    return { status: 1, stdout: "" }
  }
  assert.equal(inst.resolvePython({}, spawn), null)
})

// ---------------------------------------------------------------- findTop / download

function scratch() {
  return mkdtempSync(join(tmpdir(), "ab-installer-test-"))
}

test("findTop needs exactly one top-level directory", () => {
  const d = scratch()
  try {
    assert.throws(() => inst.findTop(d), /exactly one top-level directory/)
    mkdirSync(join(d, "ab-1.1.0"))
    assert.equal(inst.findTop(d), join(d, "ab-1.1.0"))
    writeFileSync(join(d, "stray.txt"), "x")
    assert.throws(() => inst.findTop(d), /exactly one top-level directory/)
    rmSync(join(d, "stray.txt"))
    mkdirSync(join(d, "second"))
    assert.throws(() => inst.findTop(d), /exactly one top-level directory/)
  } finally { rmSync(d, { recursive: true, force: true }) }
})

test("download refuses anything that is not https, before touching the network", async () => {
  const d = scratch()
  try {
    for (const u of ["http://example.invalid/x.tgz", "file:///etc/passwd", "ftp://example.invalid/x", "not a url"]) {
      await assert.rejects(inst.download(u, join(d, "out")), /refusing non-https|invalid URL/, u)
    }
    assert.equal(existsSync(join(d, "out")), false)
  } finally { rmSync(d, { recursive: true, force: true }) }
})

// ---------------------------------------------------------------- end to end (child process)

const BUILD_PY = `
import io, os, sys, tarfile
out, mode, work = sys.argv[1], sys.argv[2], sys.argv[3]
FAKE = b"""import json, os, sys
with open(os.path.join(os.getcwd(), "marker.json"), "w") as f:
    json.dump({"argv": sys.argv[1:], "file": os.path.abspath(__file__), "cwd": os.getcwd(), "exe": sys.executable}, f)
print("fake-install ran")
sys.exit(int(os.environ.get("FAKE_EXIT", "0")))
"""
def add(t, name, data=b"", kind=tarfile.REGTYPE, link=None):
    ti = tarfile.TarInfo(name)
    ti.type = kind
    if link:
        ti.linkname = link
    if kind == tarfile.REGTYPE:
        ti.size = len(data)
        t.addfile(ti, io.BytesIO(data))
    else:
        t.addfile(ti)
with tarfile.open(out, "w:gz") as t:
    if mode != "noscript":
        add(t, "ab-1.1.0/scripts/install.py", FAKE)
    else:
        add(t, "ab-1.1.0/README", b"x")
    if mode == "traversal":
        add(t, "../../../evil.txt", b"pwned")
    elif mode == "absolute":
        add(t, os.path.join(work, "evil-abs.txt").replace(chr(92), "/"), b"pwned")
    elif mode == "symlink":
        add(t, "ab-1.1.0/link", kind=tarfile.SYMTYPE, link=os.path.join(work, "victim").replace(chr(92), "/"))
        add(t, "ab-1.1.0/link/pwned.txt", b"pwned")
`

function setup(mode = "ok") {
  const work = realpathSync(scratch())
  const tmp = join(work, "tmp")
  const project = join(work, "proj")
  mkdirSync(tmp); mkdirSync(project); mkdirSync(join(work, "victim"))
  const bundle = join(work, "bundle.tar.gz")
  const b = spawnSync(py.executable, ["-I", "-c", BUILD_PY, bundle, mode, work], { encoding: "utf8" })
  assert.equal(b.status, 0, b.stderr)
  return { work, tmp, project, bundle, cleanup: () => rmSync(work, { recursive: true, force: true }) }
}

function runInstaller(ctx, args, extraEnv = {}, cwd = ctx.work) {
  const env = { ...process.env, TMPDIR: ctx.tmp, TEMP: ctx.tmp, TMP: ctx.tmp,
    ACTIONBOARD_BUNDLE: ctx.bundle, ACTIONBOARD_PYTHON: py.executable, ...extraEnv }
  if (extraEnv.FAKE_EXIT === undefined) delete env.FAKE_EXIT
  return spawnSync(process.execPath, [script, ...args], { env, cwd, encoding: "utf8", timeout: 120000 })
}

const leftovers = (ctx) => readdirSync(ctx.tmp)
const marker = (ctx) => JSON.parse(readFileSync(join(ctx.project, "marker.json"), "utf8"))

test("e2e: argv reaches install.py with an absolute --project; temp dir is removed", { skip: needPy }, () => {
  const ctx = setup()
  try {
    const r = runInstaller(ctx, ["--target", "codex", "--project", ctx.project, "--yes", "--dry-run", "--with", "graphify,terse"])
    assert.equal(r.status, 0, r.stdout + r.stderr)
    assert.match(r.stdout, /fake-install ran/)
    const m = marker(ctx)
    assert.deepEqual(m.argv, ["--target", "codex", "--project", ctx.project, "--dry-run", "--yes", "--with", "graphify,terse"])
    assert.ok(m.file.startsWith(ctx.tmp), "install.py must run from the temp extraction: " + m.file)
    assert.ok(m.file.includes("actionboard-install-"))
    assert.equal(realpathSync(m.cwd), realpathSync(ctx.project))
    assert.deepEqual(leftovers(ctx), [], "temp dir must be removed on success")
  } finally { ctx.cleanup() }
})

test("e2e: relative --project is made absolute and created", { skip: needPy }, () => {
  const ctx = setup()
  try {
    const r = runInstaller(ctx, ["--target=opencode", "--project=fresh/app", "--yes"])
    assert.equal(r.status, 0, r.stdout + r.stderr)
    const m = JSON.parse(readFileSync(join(ctx.work, "fresh", "app", "marker.json"), "utf8"))
    assert.deepEqual(m.argv, ["--target", "opencode", "--project", join(ctx.work, "fresh", "app"), "--yes"])
    assert.deepEqual(leftovers(ctx), [])
  } finally { ctx.cleanup() }
})

test("e2e: install.py exit code is propagated and temp dir removed on failure", { skip: needPy }, () => {
  const ctx = setup()
  try {
    const r = runInstaller(ctx, ["--target", "codex", "--project", ctx.project], { FAKE_EXIT: "3" })
    assert.equal(r.status, 3, r.stdout + r.stderr)
    assert.ok(existsSync(join(ctx.project, "marker.json")))
    assert.deepEqual(leftovers(ctx), [], "temp dir must be removed on failure")
  } finally { ctx.cleanup() }
})

test("e2e: missing bundle fails non-zero and leaves nothing behind", { skip: needPy }, () => {
  const ctx = setup()
  try {
    const r = runInstaller(ctx, ["--target", "codex", "--project", ctx.project], { ACTIONBOARD_BUNDLE: join(ctx.work, "nope.tar.gz") })
    assert.notEqual(r.status, 0)
    assert.match(r.stderr, /bundle not found/)
    assert.equal(existsSync(join(ctx.project, "marker.json")), false)
    assert.deepEqual(leftovers(ctx), [])
  } finally { ctx.cleanup() }
})

test("e2e: corrupt bundle fails cleanly", { skip: needPy }, () => {
  const ctx = setup()
  try {
    writeFileSync(ctx.bundle, "this is not a tarball")
    const r = runInstaller(ctx, ["--target", "codex", "--project", ctx.project])
    assert.notEqual(r.status, 0)
    assert.match(r.stderr, /failed to extract bundle/)
    assert.deepEqual(leftovers(ctx), [])
  } finally { ctx.cleanup() }
})

test("e2e: bundle without scripts/install.py fails cleanly", { skip: needPy }, () => {
  const ctx = setup("noscript")
  try {
    const r = runInstaller(ctx, ["--target", "codex", "--project", ctx.project])
    assert.notEqual(r.status, 0)
    assert.match(r.stderr, /does not contain scripts\/install\.py/)
    assert.deepEqual(leftovers(ctx), [])
  } finally { ctx.cleanup() }
})

test("e2e: http:// bundle URL is refused without any network access", { skip: needPy }, () => {
  const ctx = setup()
  try {
    const r = runInstaller(ctx, ["--target", "codex", "--project", ctx.project], { ACTIONBOARD_BUNDLE: "http://127.0.0.1:9/x.tar.gz" })
    assert.notEqual(r.status, 0)
    assert.match(r.stderr, /refusing non-https/)
    assert.deepEqual(leftovers(ctx), [])
  } finally { ctx.cleanup() }
})

for (const mode of ["traversal", "absolute", "symlink"]) {
  test(`e2e: hostile archive (${mode}) writes nothing outside the temp dir`, { skip: needPy }, () => {
    const ctx = setup(mode)
    try {
      const r = runInstaller(ctx, ["--target", "codex", "--project", ctx.project])
      assert.equal(existsSync(join(ctx.work, "evil.txt")), false, "../ member escaped")
      assert.equal(existsSync(join(ctx.work, "evil-abs.txt")), false, "absolute member escaped")
      assert.equal(existsSync(join(ctx.work, "victim", "pwned.txt")), false, "symlink member escaped")
      assert.deepEqual(readdirSync(join(ctx.work, "victim")), [])
      assert.deepEqual(leftovers(ctx), [])
      if (mode !== "absolute") {
        assert.notEqual(r.status, 0, "traversal/symlink archives must be rejected")
        assert.equal(existsSync(join(ctx.project, "marker.json")), false, "install.py must not run")
      }
    } finally { ctx.cleanup() }
  })
}

// EXTRACT_PY only does its own member checks on Pythons without tarfile.data_filter
// (3.9.0-3.9.16, 3.10.0-3.10.11, 3.11.0-3.11.3). Force that branch and disable the new default filter.
test("EXTRACT_PY legacy branch: symlink chain a->. , a/b->../.. , a/b/pwned.txt cannot escape",
  { skip: needPy || (process.platform === "win32" ? "tar symlinks need privileges on Windows" : false) }, () => {
    const legacy = inst.EXTRACT_PY
      .replace('hasattr(tarfile, "data_filter")', "False")
      .replace("t.extractall(dest)\n", 't.extractall(dest, filter="fully_trusted") if hasattr(tarfile, "fully_trusted_filter") else t.extractall(dest)\n')
    assert.notEqual(legacy, inst.EXTRACT_PY)
    const work = realpathSync(scratch())
    try {
      const dest = join(work, "outer", "dest")
      mkdirSync(dest, { recursive: true })
      const arc = join(work, "chain.tar.gz")
      const build = `
import io, sys, tarfile
with tarfile.open(sys.argv[1], "w:gz") as t:
    for name, kind, link in (("top/a", tarfile.SYMTYPE, "."), ("top/a/b", tarfile.SYMTYPE, "../.."), ("top/a/b/pwned.txt", tarfile.REGTYPE, None)):
        ti = tarfile.TarInfo(name); ti.type = kind
        if link: ti.linkname = link
        if kind == tarfile.REGTYPE:
            ti.size = 1; t.addfile(ti, io.BytesIO(b"x"))
        else:
            t.addfile(ti)
`
      assert.equal(spawnSync(py.executable, ["-I", "-c", build, arc]).status, 0)
      spawnSync(py.executable, ["-I", "-c", legacy, arc, dest], { encoding: "utf8" })
      assert.equal(existsSync(join(work, "outer", "pwned.txt")), false, "legacy extractor wrote outside the destination")
    } finally { rmSync(work, { recursive: true, force: true }) }
  })

test("e2e: usage errors exit 2 before any download; --help and --version exit 0", { skip: needPy }, () => {
  const ctx = setup()
  try {
    for (const args of [["--target", "claude"], ["--target", "all"], ["--global", "--project", "x", "--target", "codex"], []]) {
      const r = runInstaller(ctx, args)
      assert.equal(r.status, 2, args.join(" ") + r.stderr)
    }
    assert.equal(runInstaller(ctx, ["--help"]).status, 0)
    const v = runInstaller(ctx, ["--version"])
    assert.equal(v.status, 0)
    assert.equal(v.stdout.trim(), PKG.version)
    assert.deepEqual(leftovers(ctx), [])
  } finally { ctx.cleanup() }
})

test("package metadata: bin, no runtime dependencies, no install scripts, no shell spawn", () => {
  assert.equal(PKG.name, "@actionboard/install")
  assert.equal(PKG.bin["actionboard-install"], "bin/install.js")
  assert.ok(!PKG.dependencies || Object.keys(PKG.dependencies).length === 0)
  for (const k of ["preinstall", "install", "postinstall", "prepare"]) assert.ok(!(PKG.scripts || {})[k], k)
  assert.ok(!/shell\s*:\s*true/.test(readFileSync(script, "utf8")), "never spawn through a shell")
})
