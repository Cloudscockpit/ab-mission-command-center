#!/usr/bin/env python3
"""Install ActionBoard Agent Formation into one or more agent CLIs.

    python scripts/install.py                          # detect CLIs, ask which, install into this project
    python scripts/install.py --target opencode --project ../my-app
    python scripts/install.py --target codex --global
    python scripts/install.py --target antigravity --project . --uninstall
    python scripts/install.py --target all --project . --dry-run

Copies dist/<target> (or a fresh build when --config is given) into the CLI's
project or user directory and records every file it creates in an install
manifest. --uninstall removes only those files, and only if they are
unchanged since install. Existing files it did not create are never
overwritten unless --force is given. Claude Code installs through its plugin
marketplace, so for that target this script prints the two commands to run.

Standard library only; Python 3.9+.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import build  # noqa: E402

PLUGIN = "actionboard-v5-agentformation"
CLI_BINARIES = {"claude": "claude", "opencode": "opencode", "codex": "codex", "antigravity": "agy"}
MANIFEST = "actionboard-install.json"
HOOK_MARK = "--cli codex --event"
SHARED_DIRS = {".agents", "plugins", "skills"}
AGENTS_BEGIN, AGENTS_END = "<!-- actionboard:begin -->", "<!-- actionboard:end -->"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def python_path():
    return os.path.abspath(sys.executable)


def detect():
    return [t for t, exe in CLI_BINARIES.items() if shutil.which(exe)]


# ---------------------------------------------------------------- layouts

def plan(target, scope, project):
    """Return (mapping, manifest_path, extras): mapping is [(dist_rel_prefix, dest_dir)]."""
    home = os.path.expanduser("~")
    if target == "opencode":
        root = os.path.join(project, ".opencode") if scope == "project" else \
            os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config"), "opencode")
        config = os.path.join(project if scope == "project" else root, "opencode.json")
        return [("", root)], os.path.join(root, "actionboard", MANIFEST), {"opencode_json": config}
    if target == "codex":
        base = project if scope == "project" else home
        codex = os.path.join(base, ".codex") if scope == "project" else \
            os.environ.get("CODEX_HOME") or os.path.join(home, ".codex")
        agents_md = os.path.join(project, "AGENTS.md") if scope == "project" else os.path.join(codex, "AGENTS.md")
        return ([(".agents/", os.path.join(base, ".agents")), (".codex/", codex)],
                os.path.join(codex, "actionboard", MANIFEST),
                {"agents_md": agents_md, "hooks_dir": os.path.join(codex, "actionboard", "hooks"),
                 "config_toml": os.path.join(codex, "config.toml")})
    if target == "antigravity":
        root = os.path.join(project, ".agents", "plugins", PLUGIN) if scope == "project" else \
            os.path.join(home, ".gemini", "config", "plugins", PLUGIN)
        return [("", root)], os.path.join(root, MANIFEST), {}
    raise ValueError(target)


UNSAFE_PATH = set('"`$%!&^')


def check_path(path, what):
    """Hook commands embed these paths in shell strings; refuse metacharacters."""
    bad = sorted(UNSAFE_PATH & set(path))
    if bad:
        raise SystemExit("%s contains shell metacharacters %s: %s. Move it, or install with "
                         "a Python/project path without them." % (what, " ".join(bad), path))


def write_atomic(path, text):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".actionboard-tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    os.replace(tmp, path)


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


def unmerge_hooks(path):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    for event in list(data.get("hooks", {})):
        data["hooks"][event] = [g for g in data["hooks"][event]
                                if not any(HOOK_MARK in h.get("command", "") for h in g.get("hooks", []))]
        if not data["hooks"][event]:
            del data["hooks"][event]
    if not data.get("hooks"):
        os.remove(path)
        return
    write_atomic(path, json.dumps(data, indent=2) + "\n")


def _strip_block(text):
    start, end = text.find(AGENTS_BEGIN), text.find(AGENTS_END)
    if start == -1 or end == -1:
        return text
    return (text[:start].rstrip("\n") + "\n" + text[end + len(AGENTS_END):].lstrip("\n")).strip("\n")


def merge_agents_md(path, block, dry):
    text = ""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            text = _strip_block(fh.read())
    text = (text.rstrip("\n") + "\n\n" if text.strip() else "") + block.strip("\n") + "\n"
    if not dry:
        write_atomic(path, text)


def unmerge_agents_md(path):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as fh:
        text = _strip_block(fh.read())
    if text.strip():
        write_atomic(path, text + "\n")
    else:
        os.remove(path)


# ---------------------------------------------------------------- merges (Context7 MCP)

CONTEXT7_BEGIN, CONTEXT7_END = "# actionboard:begin context7", "# actionboard:end context7"


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


def unmerge_opencode_mcp(path, created):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    (data.get("mcp") or {}).pop("context7", None)
    if "mcp" in data and not data["mcp"]:
        del data["mcp"]
    if created and set(data) <= {"$schema"}:
        os.remove(path)
    else:
        write_atomic(path, json.dumps(data, indent=2) + "\n")


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


def unmerge_codex_mcp(path, created):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    start, end = text.find(CONTEXT7_BEGIN), text.find(CONTEXT7_END)
    if start == -1 or end == -1:
        return
    text = (text[:start].rstrip("\n") + "\n" + text[end + len(CONTEXT7_END):].lstrip("\n")).strip("\n")
    if created and not text.strip():
        os.remove(path)
    else:
        write_atomic(path, text + "\n")


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

def load_manifest(path):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return None


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
    record = {"target": target, "scope": scope, "version": version, "files": {}, "merges": [],
              "dirs": previous.get("dirs", [])}
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


def uninstall(target, scope, project):
    mapping, manifest_path, _ = plan(target, scope, project)
    record = load_manifest(manifest_path)
    if not record:
        print("no ActionBoard install manifest at " + manifest_path)
        return 1
    kept = []
    dirs = set()
    for path, digest in record["files"].items():
        if not os.path.exists(path):
            continue
        with open(path, "rb") as fh:
            if sha(fh.read()) != digest:
                kept.append(path)
                continue
        os.remove(path)
        dirs.add(os.path.dirname(path))
    for m in record.get("merges", []):
        if m["kind"] == "codex-hooks":
            unmerge_hooks(m["path"])
        elif m["kind"] == "agents-md":
            unmerge_agents_md(m["path"])
        elif m["kind"] == "codex-mcp":
            unmerge_codex_mcp(m["path"], m.get("created", False))
        elif m["kind"] == "opencode-mcp":
            unmerge_opencode_mcp(m["path"], m.get("created", False))
    os.remove(manifest_path)
    dirs.add(os.path.dirname(manifest_path))
    roots = {os.path.abspath(d) for _, d in mapping}
    for d in sorted(dirs, key=len, reverse=True):  # prune empty dirs we emptied
        d = os.path.abspath(d)
        while d not in roots and os.path.isdir(d) and not os.listdir(d):
            os.rmdir(d)
            d = os.path.dirname(d)
    for d in sorted(set(record.get("dirs", [])) | roots, key=len, reverse=True):
        # Also prune empty CLI directories another ActionBoard target created
        # (Codex and Antigravity share .agents/).
        while os.path.isdir(d) and not os.listdir(d) and (
                d in record.get("dirs", []) or d in roots or os.path.basename(d) in SHARED_DIRS):
            os.rmdir(d)
            d = os.path.dirname(d)
    for k in kept:
        print("kept (modified since install): " + k)
    print("uninstalled %s (%s)" % (target, scope))
    return 0


def claude_instructions():
    print("Claude Code installs from its plugin marketplace. In Claude Code, run:\n"
          "  /plugin marketplace add %s\n"
          "  /plugin install %s@%s" % (REPO.replace("\\", "/"), PLUGIN, PLUGIN))
    return 0


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
            status |= claude_instructions()
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
    return status


if __name__ == "__main__":
    sys.exit(main())
