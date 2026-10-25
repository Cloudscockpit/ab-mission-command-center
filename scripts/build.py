#!/usr/bin/env python3
"""Build dist/<target>/ from the neutral src/ tree.

    python scripts/build.py --target all
    python scripts/build.py --target opencode --config agentformation.config.json --out /tmp/x
    python scripts/build.py --check          # fail if dist/ differs from a fresh build

Standard library only; Python 3.9+. Output is deterministic: same src/ and
config -> byte-identical dist/.
"""

import argparse
import importlib.util
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from aflib.model import ADAPTERS, REPO, Output, Source  # noqa: E402

TARGETS = ("claude", "opencode", "codex", "antigravity")


def load_adapter(target):
    path = os.path.join(ADAPTERS, target, "adapter.py")
    spec = importlib.util.spec_from_file_location("adapter_" + target, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_config(path):
    if not path:
        return {}
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def build_target(src, target, config):
    adapter = load_adapter(target)
    out = Output()
    models = (config.get("models") or {}).get(target) or {}
    adapter.build(src, out, models)
    return out.files


def root_files(src):
    return load_adapter("claude").root_files(src)


def _encode(content):
    return content.encode("utf-8") if isinstance(content, str) else content


def write_tree(dest, files):
    if os.path.isdir(dest):
        shutil.rmtree(dest)
    for rel, content in files.items():
        path = os.path.join(dest, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(_encode(content))
        if rel.endswith((".sh", ".py")):
            os.chmod(path, 0o755)


def diff_tree(dest, files):
    """Return a list of human-readable differences between dest and files."""
    problems = []
    seen = set()
    for rel, content in files.items():
        seen.add(rel)
        path = os.path.join(dest, *rel.split("/"))
        if not os.path.exists(path):
            problems.append("missing: " + rel)
        else:
            with open(path, "rb") as fh:
                if fh.read() != _encode(content):
                    problems.append("differs: " + rel)
    if os.path.isdir(dest):
        for dp, _, fn in os.walk(dest):
            for f in fn:
                rel = os.path.relpath(os.path.join(dp, f), dest).replace(os.sep, "/")
                if rel not in seen and "__pycache__" not in rel:
                    problems.append("extra:   " + rel)
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--target", default="all", choices=TARGETS + ("all",))
    ap.add_argument("--out", default=os.path.join(REPO, "dist"),
                    help="output root; each target goes to <out>/<target>")
    ap.add_argument("--config", help="agentformation.config.json with per-target model overrides")
    ap.add_argument("--check", action="store_true", help="verify --out is up to date; write nothing")
    args = ap.parse_args(argv)

    src = Source()
    config = load_config(args.config)
    targets = TARGETS if args.target == "all" else (args.target,)
    default_out = os.path.abspath(args.out) == os.path.join(REPO, "dist")
    problems = []

    for t in targets:
        files = build_target(src, t, config)
        dest = os.path.join(args.out, t)
        if args.check:
            problems += ["%s/%s" % (t, p) for p in diff_tree(dest, files)]
        else:
            write_tree(dest, files)
            print("built %-12s %3d files -> %s" % (t, len(files), dest))

    if default_out and "claude" in targets:
        for rel, content in root_files(src).items():
            path = os.path.join(REPO, *rel.split("/"))
            if args.check:
                if not os.path.exists(path) or open(path, "rb").read() != _encode(content):
                    problems.append("root/" + rel)
            else:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "wb") as fh:
                    fh.write(_encode(content))

    if args.check:
        if problems:
            print("dist/ is stale; run python scripts/build.py --target all\n  " + "\n  ".join(problems))
            return 1
        print("dist/ is up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
