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
import shutil
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
        return [("", root)], os.path.join(root, "actionboard", MANIFEST), {}
    if target == "codex":
        base = project if scope == "project" else home
        codex = os.path.join(base, ".codex") if scope == "project" else \
            os.environ.get("CODEX_HOME") or os.path.join(home, ".codex")
        agents_md = os.path.join(project, "AGENTS.md") if scope == "project" else os.path.join(codex, "AGENTS.md")
        return ([(".agents/", os.path.join(base, ".agents")), (".codex/", codex)],
                os.path.join(codex, "actionboard", MANIFEST),
                {"agents_md": agents_md, "hooks_dir": os.path.join(codex, "actionboard", "hooks")})
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


def substitute(rel, content, extras):
    if not isinstance(content, str):
        return content
    py = python_path().replace("\\", "/")
    content = content.replace("__PYTHON__", py)
    if "hooks_dir" in extras:
        content = content.replace("__HOOKS_DIR__", extras["hooks_dir"].replace("\\", "/"))
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


# ---------------------------------------------------------------- install / uninstall

def load_manifest(path):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return None


def install(target, scope, project, files, version, force, dry):
    mapping, manifest_path, extras = plan(target, scope, project)
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
    for m in record["merges"]:
        if m["kind"] == "codex-hooks":
            text = merged_hooks(m["path"], substitute(".codex/hooks.json", files[".codex/hooks.json"], extras))
            merged.append((m["path"], lambda p=m["path"], t=text: write_atomic(p, t)))
        else:
            merged.append((m["path"], lambda p=m["path"]: merge_agents_md(p, files["AGENTS.actionboard.md"], False)))

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
        (unmerge_hooks if m["kind"] == "codex-hooks" else unmerge_agents_md)(m["path"])
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
    args = ap.parse_args(argv)

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
    return status


if __name__ == "__main__":
    sys.exit(main())
