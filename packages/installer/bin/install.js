#!/usr/bin/env node
'use strict';
// ActionBoard zero-clone installer: downloads the release bundle to a temp dir,
// runs scripts/install.py from it, then removes the temp dir. Node built-ins only.

const fs = require('fs');
const os = require('os');
const path = require('path');
const https = require('https');
const { spawnSync } = require('child_process');

const PKG = require('../package.json');
const REPO = 'Cloudscockpit/ab-mission-command-center';
const TARGETS = ['codex', 'antigravity', 'opencode'];
const MAX_REDIRECTS = 5;

const HELP = `actionboard-install ${PKG.version}

Usage: actionboard-install --target <codex|antigravity|opencode> [options]

Options:
  --target T       codex | antigravity | opencode (required)
  --global         install for the current user
  --project DIR    project directory (default: current directory)
  --uninstall      remove a previous ActionBoard install
  --dry-run        show what would change
  --yes            do not prompt
  --force          overwrite files ActionBoard did not create
  --with LIST      optional extras, e.g. graphify,terse
  --without LIST   skip optional extras
  --version, --help

Env: ACTIONBOARD_BUNDLE (local .tar.gz path or https URL), ACTIONBOARD_PYTHON (python executable)
Claude Code: use  /plugin marketplace add ${REPO}
`;

class UsageError extends Error {}

function parseArgs(argv, cwd) {
  const o = { target: null, global: false, project: null, uninstall: false,
    dryRun: false, yes: false, force: false, with: null, without: null,
    help: false, version: false };
  const need = (i, flag) => {
    if (i + 1 >= argv.length || argv[i + 1].startsWith('--')) throw new UsageError(`${flag} requires a value`);
    return argv[i + 1];
  };
  for (let i = 0; i < argv.length; i++) {
    let a = argv[i], inline = null;
    const eq = a.indexOf('=');
    if (a.startsWith('--') && eq > 0) { inline = a.slice(eq + 1); a = a.slice(0, eq); }
    const val = () => { if (inline !== null) return inline; const v = need(i, a); i++; return v; };
    switch (a) {
      case '--target': o.target = val(); break;
      case '--global': o.global = true; break;
      case '--project': o.project = val(); break;
      case '--uninstall': o.uninstall = true; break;
      case '--dry-run': o.dryRun = true; break;
      case '--yes': case '-y': o.yes = true; break;
      case '--force': o.force = true; break;
      case '--with': o.with = val(); break;
      case '--without': o.without = val(); break;
      case '--version': case '-v': o.version = true; break;
      case '--help': case '-h': o.help = true; break;
      default: throw new UsageError(`unknown argument: ${argv[i]}`);
    }
  }
  if (o.help || o.version) return o;
  if (!o.target) throw new UsageError('--target is required (codex | antigravity | opencode)');
  if (o.target === 'claude') {
    throw new UsageError(`Claude Code is installed as a plugin, not via this installer. Run:\n  /plugin marketplace add ${REPO}`);
  }
  if (!TARGETS.includes(o.target)) {
    throw new UsageError(`invalid --target "${o.target}" (allowed: ${TARGETS.join(', ')})`);
  }
  if (o.global && o.project) throw new UsageError('--global and --project are mutually exclusive');
  o.projectAbs = path.resolve(cwd, o.project || '.');
  return o;
}

function buildInstallArgs(o) {
  const a = ['--target', o.target];
  if (o.global) a.push('--global'); else a.push('--project', o.projectAbs);
  if (o.uninstall) a.push('--uninstall');
  if (o.dryRun) a.push('--dry-run');
  if (o.yes) a.push('--yes');
  if (o.force) a.push('--force');
  if (o.with) a.push('--with', o.with);
  if (o.without) a.push('--without', o.without);
  return a;
}

const PROBE = 'import sys; print(sys.version_info[:2] >= (3,9)); print(sys.executable); print(sys.prefix != sys.base_prefix)';

// Returns { cmd, prefix, executable } or null. Each candidate must really run.
function resolvePython(env = process.env, spawn = spawnSync) {
  const cands = [];
  if (env.ACTIONBOARD_PYTHON) cands.push([env.ACTIONBOARD_PYTHON, []]);
  if (process.platform === 'win32') cands.push(['py', ['-3']]);
  cands.push(['python3', []], ['python', []]);
  let venv = null;
  for (let n = 0; n < cands.length; n++) {
    const [cmd, prefix] = cands[n];
    let r;
    try { r = spawn(cmd, [...prefix, '-I', '-c', PROBE], { encoding: 'utf8', windowsHide: true }); }
    catch (_) { continue; }
    if (!r || r.error || r.status !== 0 || typeof r.stdout !== 'string') continue;
    const lines = r.stdout.split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
    if (lines[0] !== 'True' || !lines[1]) continue;
    const found = { cmd, prefix, executable: lines[1] };
    if (lines[2] === 'True') {
      if (env.ACTIONBOARD_PYTHON && n === 0) {
        found.warning = `ACTIONBOARD_PYTHON is a virtualenv interpreter (${lines[1]}); installed hooks will reference it.`;
        return found;
      }
      if (!venv) venv = found;
      continue;
    }
    return found;
  }
  if (venv) {
    venv.warning = `no non-virtualenv Python found; using ${venv.executable}. Installed hooks will reference it.`;
    return venv;
  }
  return null;
}

const PY_HINT = 'Python 3.9+ was not found. Install it from https://www.python.org/downloads/ ' +
  '(on Windows, the py launcher; on macOS: brew install python; on Linux: your package manager), ' +
  'or set ACTIONBOARD_PYTHON to a Python 3.9+ executable. ' +
  'Note: the Microsoft Store "python" stub does not count.';

function download(url, dest, redirects = 0) {
  return new Promise((resolve, reject) => {
    let u;
    try { u = new URL(url); } catch (_) { return reject(new Error(`invalid URL: ${url}`)); }
    if (u.protocol !== 'https:') return reject(new Error(`refusing non-https URL: ${url}`));
    const req = https.get(u, { headers: { 'User-Agent': `actionboard-install/${PKG.version}` } }, (res) => {
      const s = res.statusCode;
      if (s >= 300 && s < 400 && res.headers.location) {
        res.resume();
        if (redirects >= MAX_REDIRECTS) return reject(new Error('too many redirects'));
        let next;
        try { next = new URL(res.headers.location, u).toString(); } catch (_) { return reject(new Error('bad redirect')); }
        return resolve(download(next, dest, redirects + 1));
      }
      if (s === 404) {
        res.resume();
        const e = new Error(`release v${PKG.version} not found - tag not published yet (${url})`);
        e.notFound = true;
        return reject(e);
      }
      if (s !== 200) { res.resume(); return reject(new Error(`download failed: HTTP ${s} for ${url}`)); }
      const out = fs.createWriteStream(dest);
      res.pipe(out);
      out.on('finish', () => out.close(() => resolve()));
      out.on('error', (e) => { res.destroy(); reject(e); });
      res.on('error', (e) => { out.destroy(); reject(e); });
    });
    req.setTimeout(60000, () => req.destroy(new Error('download timed out')));
    req.on('error', reject);
  });
}

const EXTRACT_PY = [
  'import sys, os, tarfile',
  'src, dest = sys.argv[1], sys.argv[2]',
  'def bad(m): raise SystemExit("unsafe archive member: " + m)',
  'with tarfile.open(src) as t:',
  '    if hasattr(tarfile, "data_filter"):',
  '        t.extractall(dest, filter="data")',
  '    else:',
  '        root = os.path.realpath(dest)',
  '        inside = lambda p: p == root or p.startswith(root + os.sep)',
  '        for m in t.getmembers():',
  '            n = m.name.replace(chr(92), "/")',
  '            if os.path.isabs(m.name) or n.startswith("/") or ".." in n.split("/"): bad(m.name)',
  '            if not inside(os.path.realpath(os.path.join(dest, m.name))): bad(m.name)',
  '            if m.issym() or m.islnk() or m.isdev(): bad(m.name)',
  '        t.extractall(dest)',
  '',
].join('\n');

function rmTmp(dir) {
  if (!dir) return;
  try { fs.rmSync(dir, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 }); }
  catch (e) { process.stderr.write(`warning: could not remove ${dir}: ${e.message}\n`); }
}

function findTop(dir) {
  const ents = fs.readdirSync(dir, { withFileTypes: true });
  const dirs = ents.filter((e) => e.isDirectory());
  if (dirs.length !== 1 || ents.length !== 1) {
    throw new Error('bundle must contain exactly one top-level directory');
  }
  return path.join(dir, dirs[0].name);
}

async function main(argv) {
  let o;
  try { o = parseArgs(argv, process.cwd()); }
  catch (e) {
    if (e instanceof UsageError) { process.stderr.write(`error: ${e.message}\n\n${HELP}`); return 2; }
    throw e;
  }
  if (o.help) { process.stdout.write(HELP); return 0; }
  if (o.version) { process.stdout.write(`${PKG.version}\n`); return 0; }

  const py = resolvePython();
  if (!py) { process.stderr.write(`error: ${PY_HINT}\n`); return 1; }

  let tmp = null;
  const cleanup = () => { rmTmp(tmp); tmp = null; };
  const onSig = (code) => () => { cleanup(); process.exit(code); };
  process.on('SIGINT', onSig(130));
  process.on('SIGTERM', onSig(143));

  try {
    tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'actionboard-install-'));
    const bundleSrc = process.env.ACTIONBOARD_BUNDLE ||
      `https://codeload.github.com/${REPO}/tar.gz/refs/tags/v${PKG.version}`;
    let archive;
    if (/^https?:\/\//i.test(bundleSrc)) {
      archive = path.join(tmp, 'bundle.tar.gz');
      await download(bundleSrc, archive);
    } else {
      archive = path.resolve(bundleSrc);
      if (!fs.existsSync(archive)) throw new Error(`bundle not found: ${archive}`);
    }
    const ex = path.join(tmp, 'src');
    fs.mkdirSync(ex);
    const r = spawnSync(py.cmd, [...py.prefix, '-I', '-c', EXTRACT_PY, archive, ex],
      { stdio: ['ignore', 'inherit', 'inherit'], windowsHide: true });
    if (r.status !== 0) throw new Error('failed to extract bundle');
    const top = findTop(ex);
    const script = path.join(top, 'scripts', 'install.py');
    if (!fs.existsSync(script)) throw new Error('bundle does not contain scripts/install.py');

    if (!o.global) fs.mkdirSync(o.projectAbs, { recursive: true });
    // py.executable (sys.executable of a persistent interpreter) gets baked into installed hooks.
    const run = spawnSync(py.executable, [script, ...buildInstallArgs(o)],
      { stdio: 'inherit', cwd: o.global ? os.homedir() : o.projectAbs });
    if (run.error) throw run.error;
    return run.status === null ? 1 : run.status;
  } catch (e) {
    process.stderr.write(`error: ${e.message}\n`);
    return 1;
  } finally {
    cleanup();
  }
}

module.exports = { parseArgs, buildInstallArgs, resolvePython, download, findTop, main, EXTRACT_PY, TARGETS };

if (require.main === module) {
  main(process.argv.slice(2)).then((c) => { process.exitCode = c; },
    (e) => { process.stderr.write(`error: ${(e && e.stack) || e}\n`); process.exitCode = 1; });
}
