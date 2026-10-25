#!/usr/bin/env python3
"""Install ActionBoard Agent Formation into one or more agent CLIs.

    python scripts/install.py                          # detect CLIs, ask which, install into this project
    python scripts/install.py --target opencode --project ../my-app
    python scripts/install.py --target codex --global
    python scripts/install.py --target antigravity --project . --uninstall
    python scripts/install.py --target all --project . --dry-run
    python ab-mission-command-center/scripts/install.py --target codex --project . --cleanup

    # no clone needed to uninstall; the installer leaves a copy next to its manifest:
    python .codex/actionboard/actionboard_uninstall.py
    python .opencode/actionboard/actionboard_uninstall.py
    python .agents/plugins/actionboard-v5-agentformation/actionboard_uninstall.py

Copies dist/<target> (or a fresh build when --config is given) into the CLI's
project or user directory and records every file it creates in an install
manifest. --uninstall removes only those files, and only if they are
unchanged since install. Existing files it did not create are never
overwritten unless --force is given. Claude Code installs through its plugin
marketplace, so for that target this script prints the two commands to run.

--cleanup (git-clone one-liner) deletes this checkout after a successful install.
It refuses, leaving the clone and the install intact, unless the checkout is a
strict subdirectory of --project (of the current directory with --global), is a
clean git work tree whose origin is Cloudscockpit/ab-mission-command-center, and
no --config file lives inside it. Installed files never depend on the checkout.
actionboard_uninstall.py (copied next to each install manifest) removes an
install with no checkout present.

Standard library only; Python 3.9+.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import build  # noqa: E402
from actionboard_uninstall import (  # noqa: E402,F401
    AGENTS_BEGIN, AGENTS_END, CONTEXT7_BEGIN, CONTEXT7_END, HOOK_MARK, MANIFEST, PLUGIN,
    SHARED_DIRS, _strip_block, load_manifest, plan, sha, uninstall, unmerge_agents_md,
    unmerge_codex_mcp, unmerge_hooks, unmerge_opencode_mcp, write_atomic)

CLI_BINARIES = {"claude": "claude", "opencode": "opencode", "codex": "codex", "antigravity": "agy"}
GITHUB_REPO = "Cloudscockpit/ab-mission-command-center"
UNINSTALLER = "actionboard_uninstall.py"


def python_path():
    return os.path.abspath(sys.executable)


def detect():
    return [t for t, exe in CLI_BINARIES.items() if shutil.which(exe)]


# ---------------------------------------------------------------- layouts

UNSAFE_PATH = set('"`$%!&^')


def check_path(path, what):
    """Hook commands embed these paths in shell strings; refuse metacharacters."""
    bad = sorted(UNSAFE_PATH & set(path))
    if bad:
        raise SystemExit("%s contains shell metacharacters %s: %s. Move it, or install with "
                         "a Python/project path without them." % (what, " ".join(bad), path))


def shell_arg(path):
    """A path as one hook-command argument. Bare when it has no whitespace: some CLIs
    (agy on Windows) re-escape quotes as \\" before handing the line to cmd.exe,
    which then fails. Quoted only when a space forces it."""
    path = path.replace("\\", "/")
    return '"%s"' % path if re.search(r"\s", path) else path


def substitute(rel, content, extras):
    if not isinstance(content, str):
        return content
    py = python_path().replace("\\", "/")
    content = content.replace("__PYTHON_CMD__", shell_arg(py))
    content = content.replace("__PYTHON__", py)
    if "hooks_dir" in extras:
        content = content.replace("__HOOK_SCRIPT__",
                                  shell_arg(os.path.join(extras["hooks_dir"], "cli_hook.py")))
    return content


# ---------------------------------------------------------------- merges (codex)

def merged_hooks(path, ours):
    """Return the merged hooks.json text. Raises before anything is written."""
    data = {"hooks": {}}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            try:
                data = json.load(fh)
            except ValueError as exc:
                raise SystemExit("%s is not valid JSON (%s); fix it before installing" % (path, exc))
    data.setdefault("hooks", {})
    for event, groups in json.loads(ours)["hooks"].items():
        kept = [g for g in data["hooks"].get(event, [])
                if not any(HOOK_MARK in h.get("command", "") for h in g.get("hooks", []))]
        data["hooks"][event] = kept + groups
    return json.dumps(data, indent=2) + "\n"


def merge_agents_md(path, block, dry):
    text = ""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            text = _strip_block(fh.read())
    text = (text.rstrip("\n") + "\n\n" if text.strip() else "") + block.strip("\n") + "\n"
    if not dry:
        write_atomic(path, text)


# ---------------------------------------------------------------- merges (Context7 MCP)

def merged_opencode_mcp(path, ours):
    """opencode.json with mcp.context7 added; None when a context7 server already exists."""
    data = {"$schema": "https://opencode.ai/config.json"}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            try:
                data = json.load(fh)
            except ValueError:
                raise SystemExit(
                    "%s is not plain JSON (comments?), so the installer cannot merge into it.\n"
                    "Add the mandatory Context7 MCP by hand, then re-run:\n%s" % (path, ours))
    if (data.get("mcp") or {}).get("context7"):
        return None
    data.setdefault("mcp", {})["context7"] = json.loads(ours)["mcp"]["context7"]
    return json.dumps(data, indent=2) + "\n"


def merged_codex_mcp(path, block):
    """config.toml with a marked [mcp_servers.context7] block; None when one exists."""
    text = ""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    if re.search(r'^\s*\[mcp_servers\.("?)context7\1\]', text, re.M):
        return None
    body = "%s\n%s%s\n" % (CONTEXT7_BEGIN, block.rstrip("\n") + "\n", CONTEXT7_END)
    return (text.rstrip("\n") + "\n\n" if text.strip() else "") + body


# ---------------------------------------------------------------- optional cost tools

GRAPHIFY_SPEC = "graphifyy==0.9.95"
NOTES = {
    "graphify": (
        "Graphify indexes your code into a lightweight graph map. Agents then read that map "
        "instead of raw files, which saves input tokens and significantly reduces API cost. "
        "It is an open-source Python package (graphifyy, Apache-2.0, no telemetry) and builds "
        "the code graph offline without any API key.",
        "Install Graphify (%s) now?" % GRAPHIFY_SPEC),
    "terse": (
        "Terse output (rules derived from Caveman, bundled with ActionBoard, nothing to "
        "download) optimizes and cuts down output tokens to reduce generation cost. It applies "
        "only to background agent chatter. Mission plans, mission reports, source code, commit "
        "messages, and security reviews always stay in full, standard prose.",
        "Enable terse output for this project?"),
}
PREF_KEYS = {"graphify": "graphify", "terse": "terse_output"}


def install_graphify(dry):
    """Install graphifyy with the first available installer. Returns True on success."""
    if shutil.which("graphify"):
        print("graphify is already on PATH; not reinstalling.")
        return True
    candidates = []
    if shutil.which("uv"):
        candidates.append(["uv", "tool", "install", GRAPHIFY_SPEC])
    if shutil.which("pipx"):
        candidates.append(["pipx", "install", GRAPHIFY_SPEC])
    candidates.append([python_path(), "-m", "pip", "install", "--user", GRAPHIFY_SPEC])
    for cmd in candidates:
        print(("would run " if dry else "run ") + " ".join(cmd))
        if dry:
            return True
        if subprocess.run(cmd).returncode == 0:
            return True
    print("Graphify install failed; recon will read files instead. Try: " + " ".join(candidates[-1]))
    return False


def preferences(project, chosen, refused, interactive, dry):
    """Ask (or apply --with/--without) for Graphify and terse output, then record the
    answers in <project>/.actionboard/preferences.json for mission-preflight."""
    path = os.path.join(project, ".actionboard", "preferences.json")
    prefs = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            prefs = json.load(fh)
    for feature in ("graphify", "terse"):
        key = PREF_KEYS[feature]
        if feature in chosen:
            answer = True
        elif feature in refused:
            answer = False
        elif interactive and key not in prefs:
            note, question = NOTES[feature]
            print("\n" + note)
            try:
                answer = input(question + " [y/N] ").strip().lower() in ("y", "yes")
            except EOFError:
                print()
                continue  # no answer: stay undecided so mission-preflight asks

        else:
            continue  # undecided: mission-preflight asks inside the CLI
        if feature == "graphify" and answer:
            answer = install_graphify(dry)
        prefs[key] = "enabled" if answer else "declined"
    if prefs and not dry:
        write_atomic(path, json.dumps(prefs, indent=2, sort_keys=True) + "\n")
        print("recorded preferences in " + path)
    return prefs


# ---------------------------------------------------------------- install / uninstall

def opencode_major():
    """Installed OpenCode major version; 2 when unknown (the current release line).
    ACTIONBOARD_OPENCODE_MAJOR overrides detection."""
    forced = os.environ.get("ACTIONBOARD_OPENCODE_MAJOR")
    if forced:
        return int(forced)
    exe = shutil.which("opencode")
    if not exe:
        return 2
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=60).stdout
    except Exception:
        return 2
    m = re.search(r"(\d+)\.\d+\.\d+", out)
    return int(m.group(1)) if m else 2


def install(target, scope, project, files, version, force, dry):
    mapping, manifest_path, extras = plan(target, scope, project)
    if target == "opencode":
        # OpenCode 2.x uses the permission-hook plugin; 1.x needs the legacy one.
        files = dict(files)
        legacy = files.pop("actionboard/legacy/actionboard-guard.v1.ts", None)
        if legacy is not None and opencode_major() < 2:
            files["plugins/actionboard-guard.ts"] = legacy
            print("OpenCode 1.x detected: installing the legacy guard plugin.")
    check_path(python_path(), "The Python interpreter path")
    for _, root in mapping:
        check_path(root, "The install directory")
    previous = load_manifest(manifest_path) or {"files": {}}
    record = {"target": target, "scope": scope, "project": project, "version": version, "files": {},
              "merges": [], "dirs": previous.get("dirs", [])}
    writes, conflicts = [], []

    for rel, content in files.items():
        if target == "codex" and rel == ".codex/hooks.json":
            record["merges"].append({"kind": "codex-hooks", "path": os.path.join(mapping[1][1], "hooks.json")})
            continue
        if target == "codex" and rel == "AGENTS.actionboard.md":
            record["merges"].append({"kind": "agents-md", "path": extras["agents_md"]})
            continue
        if target == "codex" and rel == ".codex/actionboard/mcp.toml":
            record["merges"].append({"kind": "codex-mcp", "path": extras["config_toml"]})
            continue
        if target == "opencode" and rel == "actionboard/mcp.json":
            record["merges"].append({"kind": "opencode-mcp", "path": extras["opencode_json"]})
            continue
        prefix, dest_root = next((p, d) for p, d in mapping if rel.startswith(p))
        dest = os.path.normpath(os.path.join(dest_root, *rel[len(prefix):].split("/")))
        if os.path.commonpath([dest, os.path.normpath(dest_root)]) != os.path.normpath(dest_root):
            raise SystemExit("refusing to write outside %s: %s" % (dest_root, rel))
        data = substitute(rel, content, extras)
        data = data.encode("utf-8") if isinstance(data, str) else data
        if os.path.exists(dest) and dest not in previous["files"] and not force:
            with open(dest, "rb") as fh:
                if fh.read() != data:
                    conflicts.append(dest)
                    continue
        writes.append((dest, data))
        record["files"][dest] = sha(data)

    with open(os.path.join(HERE, UNINSTALLER), "rb") as fh:
        uninstaller = fh.read()
    dest = os.path.join(os.path.dirname(manifest_path), UNINSTALLER)
    if os.path.exists(dest) and dest not in previous["files"] and not force:
        with open(dest, "rb") as fh:
            if fh.read() != uninstaller:
                conflicts.append(dest)
    writes.append((dest, uninstaller))
    record["files"][dest] = sha(uninstaller)

    if conflicts:
        print("Refusing to overwrite files ActionBoard did not create (use --force):")
        for c in conflicts:
            print("  " + c)
        return 1

    # Build merged configs up front so a malformed user file aborts before any write.
    merged = []
    prior = {(m["kind"], m["path"]): m for m in previous.get("merges", [])}
    for m in list(record["merges"]):
        old = prior.get((m["kind"], m["path"]))
        if m["kind"] == "codex-hooks":
            text = merged_hooks(m["path"], substitute(".codex/hooks.json", files[".codex/hooks.json"], extras))
        elif m["kind"] == "agents-md":
            merged.append((m["path"], lambda p=m["path"]: merge_agents_md(p, files["AGENTS.actionboard.md"], False)))
            continue
        else:  # Context7: never touch a server the user configured themselves
            m["created"] = old["created"] if old else not os.path.exists(m["path"])
            if m["kind"] == "codex-mcp":
                text = merged_codex_mcp(m["path"], files[".codex/actionboard/mcp.toml"])
            else:
                text = merged_opencode_mcp(m["path"], files["actionboard/mcp.json"])
            if text is None:
                if not old:  # configured by the user: leave it, and do not remove it later
                    record["merges"].remove(m)
                    print("Context7 MCP already configured in %s; leaving it as is." % m["path"])
                continue
        merged.append((m["path"], lambda p=m["path"], t=text: write_atomic(p, t)))

    for dest, data in writes:
        print(("would write " if dry else "write ") + dest)
        if not dry:
            d = os.path.dirname(dest)
            while not os.path.isdir(d):
                record["dirs"].append(d)
                d = os.path.dirname(d)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as fh:
                fh.write(data)
    # Drop files from an older install that this version no longer ships.
    for stale in set(previous["files"]) - set(record["files"]):
        if not dry and os.path.exists(stale):
            os.remove(stale)

    # Manifest before merges, so a failed merge can still be uninstalled.
    if not dry:
        record["dirs"] = sorted(set(record["dirs"]))
        write_atomic(manifest_path, json.dumps(record, indent=2, sort_keys=True) + "\n")
    for path, apply in merged:
        print(("would merge " if dry else "merge ") + path)
        if not dry:
            apply()
    print("%s %s (%s) -> %s" % ("checked" if dry else "installed", target, scope, mapping[0][1]))
    return 0


def claude_instructions(source=None):
    print("Claude Code installs from its plugin marketplace. In Claude Code, run:\n"
          "  /plugin marketplace add %s\n"
          "  /plugin install %s@%s" % (source or REPO.replace("\\", "/"), PLUGIN, PLUGIN))
    return 0


# ---------------------------------------------------------------- --cleanup

ORIGIN_RE = re.compile(r"^(https://([^/@]+@)?github\.com/|git@github\.com:|ssh://git@github\.com/)%s(\.git)?/?$"
                       % re.escape(GITHUB_REPO), re.I)


def _inside(path, parent):
    """True when path is a strict descendant of parent (both already real paths)."""
    path, parent = os.path.normcase(path), os.path.normcase(parent)
    try:
        return path != parent and os.path.commonpath([path, parent]) == parent
    except ValueError:
        return False


def _git(repo, *args):
    return subprocess.run(["git", "-C", repo] + list(args), capture_output=True, text=True, timeout=120)


def cleanup_refusal(repo, project, config, scope):
    """Why --cleanup must not delete repo, or None when every guard holds."""
    repo = os.path.realpath(repo)
    base = os.path.realpath(os.getcwd() if scope == "global" else project)
    if not _inside(repo, base):
        return "%s is not a subdirectory of %s" % (repo, base)
    if config:
        cfg = os.path.realpath(config)
        if cfg == repo or _inside(cfg, repo):
            return "--config %s is inside %s" % (config, repo)
    if not shutil.which("git"):
        return "git is not available to verify the checkout"
    if not os.path.exists(os.path.join(repo, ".git")):
        return "%s is not a git checkout" % repo
    try:
        origin = _git(repo, "remote", "get-url", "origin")
        status = _git(repo, "status", "--porcelain", "--ignored")
        unpushed = _git(repo, "rev-list", "--count", "HEAD", "--not", "--remotes")
        stash = _git(repo, "stash", "list")
    except (OSError, subprocess.SubprocessError):
        return "git could not inspect %s" % repo
    if origin.returncode != 0 or not ORIGIN_RE.match(origin.stdout.strip()):
        return "origin of %s is not %s" % (repo, GITHUB_REPO)
    if status.returncode != 0:
        return "git could not inspect %s" % repo
    lines = [ln for ln in status.stdout.splitlines() if ln.strip()]
    if any(not ln.startswith("!!") for ln in lines):
        return "%s has uncommitted or untracked changes" % repo
    if any(not re.search(r"(^|/)__pycache__/?$|\.pyc$", ln[3:].strip().strip('"')) for ln in lines):
        return "ignored files present in %s" % repo
    if unpushed.returncode != 0 or unpushed.stdout.strip() != "0":
        return "unpushed commits in %s" % repo
    if stash.returncode != 0 or stash.stdout.strip():
        return "git stash entries in %s" % repo
    return None


def _clear_readonly(func, path, _exc):
    os.chmod(path, stat.S_IWRITE)
    func(path)


def remove_tree(path):
    """rmtree that clears read-only bits (git objects on Windows) and retries."""
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_clear_readonly)
    else:
        shutil.rmtree(path, onerror=_clear_readonly)


def cleanup(repo, project, config, scope, remove=None):
    """Delete the installer's own checkout if every guard passes. Never raises."""
    remove = remove or remove_tree
    reason = cleanup_refusal(repo, project, config, scope)
    if reason:
        print("--cleanup skipped, checkout left in place: " + reason)
        return False
    repo = os.path.realpath(repo)
    try:
        cwd = os.path.realpath(os.getcwd())
        if cwd == repo or _inside(cwd, repo):
            os.chdir(os.path.dirname(repo))
        remove(repo)
    except OSError as exc:
        print("--cleanup could not remove %s (%s). Delete it yourself, e.g. %s" % (
            repo, exc, 'rmdir /s /q "%s"' % repo if os.name == "nt" else 'rm -rf "%s"' % repo))
        return False
    print("removed " + repo)
    return True


def target_files(target, config):
    if config:
        src = build.Source()
        files = build.build_target(src, target, build.load_config(config))
        files["_version"] = src.version
    else:
        root = os.path.join(REPO, "dist", target)
        if not os.path.isdir(root):
            raise SystemExit("dist/%s is missing; run python scripts/build.py first" % target)
        files = {}
        for dp, _, fn in os.walk(root):
            for f in sorted(fn):
                full = os.path.join(dp, f)
                rel = os.path.relpath(full, root).replace(os.sep, "/")
                with open(full, "rb") as fh:
                    data = fh.read()
                try:
                    files[rel] = data.decode("utf-8")
                except UnicodeDecodeError:
                    files[rel] = data
        with open(os.path.join(REPO, "src", "VERSION"), encoding="utf-8") as fh:
            files["_version"] = fh.read().strip()
    return files


def main(argv=None):
    ap = argparse.ArgumentParser(description="Install ActionBoard Agent Formation into agent CLIs.")
    ap.add_argument("--target", choices=build.TARGETS + ("all",),
                    help="CLI to install into (default: ask, from the CLIs found on PATH)")
    scope = ap.add_mutually_exclusive_group()
    scope.add_argument("--global", dest="glob", action="store_true", help="install for the current user")
    scope.add_argument("--project", default=".", help="project directory (default: .)")
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--config", help="agentformation.config.json with per-target model overrides")
    ap.add_argument("--force", action="store_true", help="overwrite files ActionBoard did not create")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--cleanup", action="store_true",
                    help="after a successful install, delete this checkout (guarded)")
    ap.add_argument("--yes", action="store_true", help="do not prompt")
    ap.add_argument("--with", dest="with_", default="", metavar="graphify,terse",
                    help="opt in without a prompt: install Graphify and/or enable terse output")
    ap.add_argument("--without", default="", metavar="graphify,terse",
                    help="opt out without a prompt")
    args = ap.parse_args(argv)
    chosen = {x.strip() for x in args.with_.split(",") if x.strip()}
    refused = {x.strip() for x in args.without.split(",") if x.strip()}
    if (chosen | refused) - set(NOTES):
        raise SystemExit("--with/--without accept: " + ", ".join(sorted(NOTES)))

    if sys.version_info < (3, 9):
        raise SystemExit("Python 3.9+ is required")
    if args.target == "all":
        targets = list(build.TARGETS)
    elif args.target:
        targets = [args.target]
    else:
        found = detect()
        if not found:
            raise SystemExit("No supported CLI found on PATH (claude, opencode, codex, agy). Use --target.")
        print("Found: " + ", ".join(found))
        if args.yes:
            targets = found
        else:
            answer = input("Install into which? [%s] " % ",".join(found)).strip()
            targets = [t.strip() for t in answer.split(",")] if answer else found
            bad = [t for t in targets if t not in build.TARGETS]
            if bad:
                raise SystemExit("unknown target(s): " + ", ".join(bad))

    scope_name = "global" if args.glob else "project"
    project = os.path.abspath(args.project)
    status = 0
    for t in targets:
        if t == "claude":
            status |= claude_instructions(GITHUB_REPO if args.cleanup else None)
        elif args.uninstall:
            status |= uninstall(t, scope_name, project)
        else:
            files = target_files(t, args.config)
            version = files.pop("_version")
            status |= install(t, scope_name, project, files, version, args.force, args.dry_run)

    # Graphify and terse output are per project and always opt-in: ask here, or let
    # mission-preflight ask inside the CLI when this run is non-interactive.
    if not args.uninstall and status == 0 and scope_name == "project":
        interactive = not args.yes and sys.stdin.isatty()
        preferences(project, chosen, refused, interactive, args.dry_run)
    if args.cleanup and not args.uninstall and not args.dry_run:
        if status == 0 and any(t != "claude" for t in targets):
            cleanup(REPO, project, args.config, scope_name)
        elif status == 0:
            print("--cleanup skipped: nothing is installed for claude, checkout left in place")
    return status


if __name__ == "__main__":
    sys.exit(main())
