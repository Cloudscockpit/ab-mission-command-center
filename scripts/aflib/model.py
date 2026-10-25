"""Load the neutral src/ tree and render it for one target."""

import json
import os
import re
from collections import OrderedDict

from . import frontmatter, render

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(REPO, "src")
ADAPTERS = os.path.join(REPO, "adapters")
TEXT_EXT = (".md", ".json", ".py", ".sh", ".yaml", ".yml", ".ts", ".toml", ".txt", ".rules")

CAPABILITIES = ("read", "write", "edit", "bash", "webfetch", "websearch", "delegate", "skills")


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read().replace("\r\n", "\n")


def _tree(root):
    out = OrderedDict()
    for dp, dn, fn in sorted(os.walk(root)):
        dn.sort()
        for f in sorted(fn):
            full = os.path.join(dp, f)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            if "__pycache__" in rel:
                continue
            out[rel] = _read(full) if f.endswith(TEXT_EXT) else open(full, "rb").read()
    return out


class Doc:
    def __init__(self, name, meta, body):
        self.name, self.meta, self.body = name, meta, body

    def targets(self):
        return self.meta.get("targets")

    def for_target(self, target):
        t = self.targets()
        return t is None or target in t


class Skill(Doc):
    def __init__(self, name, meta, body, files):
        Doc.__init__(self, name, meta, body)
        self.files = files  # rel path -> text|bytes, excluding SKILL.md


class Source:
    def __init__(self, root=SRC):
        self.root = root
        self.version = _read(os.path.join(root, "VERSION")).strip()
        self.package = json.loads(_read(os.path.join(root, "package.json")))
        self.agents = self._docs("agents")
        self.commands = self._docs("commands")
        self.skills = []
        sroot = os.path.join(root, "skills")
        for name in sorted(os.listdir(sroot)):
            files = _tree(os.path.join(sroot, name))
            meta, body = frontmatter.split(files.pop("SKILL.md"))
            if meta.get("name") != name:
                raise ValueError("skill %s: name must match its directory" % name)
            self.skills.append(Skill(name, meta, body, files))
        self.hooks_core = _tree(os.path.join(root, "hooks", "core"))
        PARTIALS.clear()
        pdir = os.path.join(root, "partials")
        if os.path.isdir(pdir):
            for f in sorted(os.listdir(pdir)):
                if f.endswith(".md"):
                    PARTIALS[f[:-3]] = _read(os.path.join(pdir, f))
        for a in self.agents:
            caps = a.meta.get("capabilities") or {}
            unknown = set(caps) - set(CAPABILITIES)
            if unknown:
                raise ValueError("agent %s: unknown capabilities %s" % (a.name, sorted(unknown)))

    def _docs(self, kind):
        out = []
        d = os.path.join(self.root, kind)
        for f in sorted(os.listdir(d)):
            if f.endswith(".md"):
                meta, body = frontmatter.split(_read(os.path.join(d, f)))
                if meta.get("name") != f[:-3]:
                    raise ValueError("%s/%s: name must match file name" % (kind, f))
                out.append(Doc(f[:-3], meta, body))
        return out

    def agent(self, name):
        return next(a for a in self.agents if a.name == name)


def caps(agent):
    c = dict.fromkeys(CAPABILITIES, False)
    c.update(agent.meta.get("capabilities") or {})
    return c


def bash_mode(value):
    """Normalise a bash capability to allow|ask|deny (pattern maps pass through)."""
    if isinstance(value, dict):
        return value
    if value is True:
        return "allow"
    if value in (False, None, ""):
        return "deny"
    return value


def target_meta(meta, target, drop=("name", "description", "targets", "role", "model_tier",
                                    "capabilities", "invocation")):
    """Neutral keys removed, then the x-<target> overrides merged in."""
    out = OrderedDict()
    for k, v in meta.items():
        if k in drop or k.startswith("x-"):
            continue
        out[k] = v
    out.update(meta.get("x-" + target) or {})
    return out


PARTIALS = {}  # src/partials/<name>.md, filled by Source()


def _include(text, where):
    def repl(m):
        name = m.group(1)
        if name not in PARTIALS:
            raise KeyError("unknown partial {{partial:%s}} in %s" % (name, where))
        return PARTIALS[name].rstrip("\n")
    return re.sub(r"\{\{partial:([a-z_]+)\}\}", repl, text)


def render_text(text, target, values, where):
    """Partials first (so they get the same conditionals and placeholders), then
    conditional blocks, then placeholders."""
    return render.fill(render.strip_conditionals(_include(text, where), target), values, where)


def render_tree(files, target, values, where):
    out = OrderedDict()
    for rel, content in files.items():
        if isinstance(content, str) and not rel.endswith(".py"):
            content = render_text(content, target, values, "%s/%s" % (where, rel))
        out[rel] = content
    return out


class Output:
    """Collects files for one target; written atomically by build.py."""

    def __init__(self):
        self.files = OrderedDict()

    def add(self, path, content):
        if path in self.files:
            raise ValueError("duplicate output path: " + path)
        if isinstance(content, str) and not content.endswith("\n"):
            content += "\n"
        self.files[path] = content

    def add_tree(self, prefix, files):
        for rel, content in files.items():
            self.add(prefix + rel, content)


def glossary_section(label, glossary, agent=None):
    """Glossary rows are (action, tool, capability); `a|b` means either one.
    With an agent, rows for capabilities it lacks are dropped."""
    have = caps(agent) if agent else None
    rows = "\n".join("| %s | %s |" % (k, v) for k, v, need in glossary
                     if have is None or any(have.get(n) not in (False, None, "deny")
                                            for n in need.split("|")))
    return ("\n## Tool glossary (%s)\n\nThis formation was written for several CLIs. On %s, "
            "use these tools:\n\n| Action | Tool |\n|---|---|\n%s\n" % (label, label, rows))


def adapter_file(*parts):
    return _read(os.path.join(ADAPTERS, *parts))


def adapter_tree(*parts):
    return _tree(os.path.join(ADAPTERS, *parts))
