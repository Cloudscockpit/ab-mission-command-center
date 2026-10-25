"""Claude Code: a plugin (dist/claude) plus a single-plugin marketplace at the
repository root (.claude-plugin/marketplace.json -> ./dist/claude)."""

import json
from collections import OrderedDict

from aflib import frontmatter
from aflib.common import context7_json
from aflib.model import adapter_file, adapter_tree, bash_mode, caps, render_text, render_tree, target_meta

NAME = "claude"
LABEL = "Claude Code"
MODELS = {"strong": "opus", "fast": "sonnet", "inherit": "inherit"}

TOOLS = {
    "dispatch": "the `Agent` tool",
    "parallel": "Use multiple `Agent` tool calls in a single message.",
    "skill": "the `Skill` tool",
    "skill_creator": "the `skill-creator` skill via the `Skill` tool",
    "reload": "after /reload-plugins",
    "read": "the `Read` tool",
    "glob": "`Glob`",
    "grep": "`Grep`",
    "shell": "`Bash`",
    "webfetch": "`WebFetch`",
}


def values(skill=None):
    v = {"tool:" + k: t for k, t in TOOLS.items()}
    v["skills_root"] = "${CLAUDE_PLUGIN_ROOT}/skills"
    v["args"] = "$ARGUMENTS"
    if skill:
        v["skill_dir"] = "${CLAUDE_PLUGIN_ROOT}/skills/" + skill
    return v


def tools(agent):
    c = caps(agent)
    bash = bash_mode(c["bash"])
    out = []
    if c["read"]:
        out.append("Read")
    if c["write"]:
        out.append("Write")
    if c["edit"]:
        out.append("Edit")
    if bash != "deny":
        out.append("Bash")
    if c["read"]:
        out += ["Glob", "Grep"]
    if c["webfetch"]:
        out.append("WebFetch")
    if c["websearch"]:
        out.append("WebSearch")
    if c["delegate"]:
        out.append("Agent")
    if c["skills"]:
        out.append("Skill")
    return out


def build(src, out, models):
    models = dict(MODELS, **models)
    for a in src.agents:
        if not a.for_target(NAME):
            continue
        meta = OrderedDict(name=a.name, description=a.meta["description"])
        meta["tools"] = ", ".join(tools(a))
        meta["model"] = models[a.meta.get("model_tier", "inherit")]
        meta.update(target_meta(a.meta, NAME))
        out.add("agents/%s.md" % a.name, frontmatter.join(
            meta, render_text(a.body, NAME, values(), "agents/" + a.name)))

    for c in src.commands:
        meta = target_meta(c.meta, NAME, drop=("name", "targets", "agent"))
        out.add("commands/%s.md" % c.name, frontmatter.join(
            meta, render_text(c.body, NAME, values(), "commands/" + c.name)))

    for s in src.skills:
        if not s.for_target(NAME):
            continue
        meta = OrderedDict(name=s.name, description=s.meta["description"])
        inv = s.meta.get("invocation")
        if inv == "model":
            meta["user-invocable"] = False
        elif inv == "user":
            meta["disable-model-invocation"] = True
        for k, v in target_meta(s.meta, NAME).items():
            meta[k] = render_text(v, NAME, values(s.name), s.name) if isinstance(v, str) else v
        vals = values(s.name)
        out.add("skills/%s/SKILL.md" % s.name, frontmatter.join(
            meta, render_text(s.body, NAME, vals, "skills/" + s.name)))
        out.add_tree("skills/%s/" % s.name, render_tree(s.files, NAME, vals, "skills/" + s.name))

    out.add("hooks/hooks.json", adapter_file("claude", "hooks", "hooks.json"))
    out.add("hooks/run-hook.sh", adapter_file("claude", "hooks", "run-hook.sh"))
    out.add_tree("hooks/", adapter_tree("common", "hooks"))
    out.add_tree("hooks/core/", src.hooks_core)

    p = src.package
    manifest = OrderedDict([
        ("name", p["name"]), ("displayName", p["displayName"]), ("version", src.version),
        ("description", p["description"]), ("author", p["author"]),
        ("homepage", p["homepage"]), ("repository", p["repository"]),
        ("license", p["license"]), ("keywords", p["keywords"]),
    ])
    out.add(".claude-plugin/plugin.json", json.dumps(manifest, indent=2, ensure_ascii=False))
    out.add(".mcp.json", context7_json("claude"))


def root_files(src):
    """Files written at the repository root (outside dist/)."""
    p = src.package
    market = OrderedDict([
        ("$schema", "https://anthropic.com/claude-code/marketplace.schema.json"),
        ("name", p["name"]),
        ("description", "Single-plugin marketplace for %s: mission-style multi-agent "
                        "orchestration with a Black planner agent and four specialist "
                        "agents (Red/Blue/Green/Yellow)." % p["displayName"]),
        ("owner", p["owner"]),
        ("plugins", [OrderedDict([
            ("name", p["name"]), ("displayName", p["displayName"]),
            ("description", p["description"]), ("author", p["author"]),
            ("category", p["category"]), ("source", "./dist/claude"),
            ("version", src.version), ("license", p["license"]),
            ("homepage", p["homepage"]), ("repository", p["repository"]),
            ("keywords", p["keywords"]),
        ])]),
    ])
    return {".claude-plugin/marketplace.json": json.dumps(market, indent=2, ensure_ascii=False) + "\n"}
