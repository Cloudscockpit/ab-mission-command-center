"""OpenCode: dist/opencode mirrors a `.opencode/` directory (project) or
`~/.config/opencode/` (global). Black Agent is a primary agent that the
/start-mission command runs as, so dispatch is one level deep (OpenCode's
default subagent_depth of 1 is enough)."""

import json
from collections import OrderedDict

from aflib import frontmatter
from aflib.common import agent_body, plain_skill
from aflib.model import adapter_file, adapter_tree, bash_mode, caps, render_text

NAME = "opencode"
LABEL = "OpenCode"
MODELS = {}  # omitted -> the agent inherits the session model

TOOLS = {
    "dispatch": "the `task` tool, with `subagent_type` set to the agent name",
    "parallel": "Issue several `task` tool calls in a single message.",
    "skill": "the `skill` tool",
    "skill_creator": ("a new `.opencode/skills/<name>/SKILL.md` (Agent Skills format: `name` "
                      "and `description` frontmatter) written with the `write` tool"),
    "reload": "after OpenCode is restarted",
    "read": "the `read` tool",
    "glob": "`glob`",
    "grep": "`grep`",
    "shell": "`bash`",
    "webfetch": "`webfetch`",
}

GLOSSARY = [
    ("Read a file", "`read`", "read"), ("Create a file", "`write`", "write"), ("Edit a file", "`edit`", "edit"),
    ("Find files by name", "`glob`", "read"), ("Search file contents", "`grep`", "read"),
    ("Run a shell command", "`bash`", "bash"), ("Fetch a URL", "`webfetch`", "webfetch"),
    ("Search the web", "`websearch`", "websearch"), ("Dispatch a subagent", "`task` (`subagent_type`)", "delegate"),
    ("Load a skill", "`skill`", "skills"),
]

# Static asks for the rules the guard plugin hands back to OpenCode (see
# adapters/opencode/plugins/actionboard-guard.ts). Last matching rule wins.
OPENSHELL_BASH = OrderedDict([
    ("openshell policy set *--global*", "ask"),
    ("openshell workspace delete*", "ask"),
    ("openshell *:full*", "ask"),
    ("openshell sandbox delete *--all*", "deny"),
])


def _flag(on):
    return "allow" if on else "deny"


def permission(src, agent):
    c = caps(agent)
    p = OrderedDict()
    p["read"] = _flag(c["read"])
    p["edit"] = _flag(c["write"] or c["edit"])
    bash = bash_mode(c["bash"])
    if bash == "deny":
        p["bash"] = "deny"
    else:
        rules = OrderedDict(bash) if isinstance(bash, dict) else OrderedDict([("*", bash)])
        rules.update(OPENSHELL_BASH)
        p["bash"] = rules
    p["webfetch"] = _flag(c["webfetch"])
    p["websearch"] = _flag(c["websearch"])
    if c["delegate"]:
        task = OrderedDict([("*", "deny")])
        for other in src.agents:
            if other.meta.get("role") == "subagent" and other.for_target(NAME):
                task[other.name] = "allow"
        p["task"] = task
    else:
        p["task"] = "deny"
    p["skill"] = _flag(c["skills"])
    return p


def build(src, out, models):
    models = dict(MODELS, **models)
    vals = {"tool:" + k: t for k, t in TOOLS.items()}
    vals.update(args="$ARGUMENTS", skill_dir="<skill-dir>", skills_root="<skill-dir>/..")

    for a in src.agents:
        if not a.for_target(NAME):
            continue
        meta = OrderedDict(description=a.meta["description"])
        meta["mode"] = "primary" if a.meta.get("role") == "primary" else "subagent"
        model = models.get(a.meta.get("model_tier", "inherit"))
        if model:
            meta["model"] = model
        meta["permission"] = permission(src, a)
        meta.update((k, v) for k, v in a.meta.get("x-" + NAME, {}).items())
        out.add("agents/%s.md" % a.name,
                frontmatter.join(meta, agent_body(a, NAME, TOOLS, LABEL, GLOSSARY)))

    for c in src.commands:
        meta = OrderedDict(description=c.meta["description"])
        if c.meta.get("agent"):
            meta["agent"] = c.meta["agent"]
        out.add("commands/%s.md" % c.name,
                frontmatter.join(meta, render_text(c.body, NAME, vals, "commands/" + c.name)))

    for s in src.skills:
        if not s.for_target(NAME):
            continue
        text, files = plain_skill(s, NAME, TOOLS)
        out.add("skills/%s/SKILL.md" % s.name, text)
        out.add_tree("skills/%s/" % s.name, files)

    out.add("plugins/actionboard-guard.ts", adapter_file("opencode", "plugins", "actionboard-guard.ts"))
    out.add_tree("actionboard/hooks/core/", src.hooks_core)
    out.add("actionboard/config.json", json.dumps(
        OrderedDict([("version", src.version), ("python", "__PYTHON__")]), indent=2))
