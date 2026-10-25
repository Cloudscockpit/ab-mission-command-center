#!/usr/bin/env python3
"""Remove an ActionBoard Agent Formation install. No clone or build step needed.

    python actionboard_uninstall.py                                   # run from the installed copy: reads the manifest next to it
    python actionboard_uninstall.py --target codex --project .
    python actionboard_uninstall.py --target opencode --global

Removes only the files recorded in the install manifest, and only if they are
unchanged since install, then undoes the config merges it made. install.py
copies this file next to the manifest for codex, opencode and antigravity.

Standard library only; Python 3.9+.
"""

import argparse
import hashlib
import json
import os
import sys

PLUGIN = "actionboard-v5-agentformation"
MANIFEST = "actionboard-install.json"
HOOK_MARK = "--cli codex --event"
SHARED_DIRS = {".agents", "plugins", "skills"}
AGENTS_BEGIN, AGENTS_END = "<!-- actionboard:begin -->", "<!-- actionboard:end -->"
CONTEXT7_BEGIN, CONTEXT7_END = "# actionboard:begin context7", "# actionboard:end context7"
TARGETS = ("opencode", "codex", "antigravity")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_atomic(path, text):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".actionboard-tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    os.replace(tmp, path)


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


def load_manifest(path):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return None


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


def unmerge_agents_md(path):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as fh:
        text = _strip_block(fh.read())
    if text.strip():
        write_atomic(path, text + "\n")
    else:
        os.remove(path)


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


def prune_pycache(paths):
    """Remove __pycache__ dirs Python created beside manifest .py files. A dir is touched only
    when every entry is <stem>.*.pyc of a recorded .py in its parent; pycs of kept .py stay."""
    stems = {}
    for p in paths:
        if p.endswith(".py"):
            name = os.path.basename(p)[:-3]
            stems.setdefault(os.path.dirname(p), {})[name] = p
    for parent, names in stems.items():
        cache = os.path.join(parent, "__pycache__")
        if not os.path.isdir(cache):
            continue
        entries = os.listdir(cache)
        owner = {}
        for e in entries:
            stem = e.split(".", 1)[0]
            if not e.endswith(".pyc") or stem not in names or not os.path.isfile(os.path.join(cache, e)):
                break
            owner[e] = names[stem]
        else:
            for e, py in owner.items():
                if not os.path.exists(py):
                    os.remove(os.path.join(cache, e))
            if not os.listdir(cache):
                os.rmdir(cache)


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
    prune_pycache(record["files"])
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


def main(argv=None):
    ap = argparse.ArgumentParser(description="Remove an ActionBoard Agent Formation install.")
    ap.add_argument("--target", choices=TARGETS,
                    help="CLI to remove (default: read from the manifest next to this script)")
    scope = ap.add_mutually_exclusive_group()
    scope.add_argument("--global", dest="glob", action="store_true", help="user-level install")
    scope.add_argument("--project", help="project directory of the install")
    args = ap.parse_args(argv)
    if args.target:
        scope_name = "global" if args.glob else "project"
        return uninstall(args.target, scope_name, os.path.abspath(args.project or "."))
    local = load_manifest(os.path.join(os.path.dirname(os.path.abspath(__file__)), MANIFEST))
    if not local or "target" not in local:
        raise SystemExit("no manifest next to this script; pass --target and --global or --project")
    return uninstall(local["target"], local["scope"], local.get("project") or os.path.abspath("."))


if __name__ == "__main__":
    sys.exit(main())
