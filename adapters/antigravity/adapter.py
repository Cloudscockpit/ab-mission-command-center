"""Google Antigravity CLI (agy): dist/antigravity is a plugin directory
(plugin.json, skills/, agents/, hooks.json, rules/AGENTS.md).

agy has no custom commands (workflows are deprecated), so /start-mission ships
as the `start-mission` skill, which agy exposes as `/start-mission`. The
session plays Black Agent; black-agent is also shipped as a main agent for
`agy --agent black-agent`. Hooks support "ask" natively.

__PYTHON_CMD__ in hooks.json is filled in by scripts/install.py; hook commands run
from the plugin folder, so paths are relative to it.
"""

import json
from collections import OrderedDict

from aflib import frontmatter
from aflib.common import agent_body, command_as_skill, context7_json, plain_skill
from aflib.model import adapter_file, adapter_tree, bash_mode, caps

NAME = "antigravity"
LABEL = "Antigravity CLI"
MODELS = {"strong": "pro", "fast": "flash", "inherit": "inherit"}

TOOLS = {
    "dispatch": "`invoke_subagent` with the agent name",
    "parallel": "Call `invoke_subagent` for every independent agent in the same turn.",
    "skill": "its name (`/skill-name`), or by reading its SKILL.md with `view_file`",
    "skill_creator": ("a new `.agents/skills/<name>/SKILL.md` (`name` and `description` "
                      "frontmatter) written with `write_to_file`"),
    "reload": "after the Antigravity CLI is restarted",
    "read": "`view_file`",
    "glob": "`find_by_name`",
    "grep": "`grep_search`",
    "shell": "`run_command`",
    "webfetch": "`read_url_content`",
}

GLOSSARY = [
    ("Read a file", "`view_file`", "read"), ("Create a file", "`write_to_file`", "write"),
    ("Edit a file", "`replace_file_content` / `multi_replace_file_content`", "edit"),
    ("Find files by name", "`find_by_name`, `list_dir`", "read"), ("Search file contents", "`grep_search`", "read"),
    ("Run a shell command", "`run_command`", "bash"), ("Fetch a URL", "`read_url_content`", "webfetch"),
    ("Search the web", "`search_web`", "websearch"), ("Dispatch a subagent", "`invoke_subagent`", "delegate"),
    ("Load a skill", "`/skill-name` or `view_file` on its SKILL.md", "skills"),
]

RULES = """\
# ActionBoard V5 Agent Formation

Run `/start-mission <objective>` to plan a mission: this session acts as Black Agent,
dispatches `green-agent` for recon, drafts the Mission Brief, Agent Assignments (with file
ownership), Skills Gap and Risk Register, then STOPS for go/no-go. After "go" it dispatches
`red-agent`, `blue-agent` and `yellow-agent` with `invoke_subagent`.

- Only dispatch the ActionBoard agents when a mission is running.
- Specialists never dispatch other agents and never commit.
- `openshell` commands are checked by the ActionBoard PreToolUse hook.
"""


def tools(agent):
    c = caps(agent)
    out = []
    if c["read"]:
        out += ["view_file", "list_dir", "find_by_name", "grep_search"]
    if c["write"]:
        out.append("write_to_file")
    if c["edit"]:
        out += ["replace_file_content", "multi_replace_file_content"]
    if bash_mode(c["bash"]) != "deny":
        out.append("run_command")
    if c["webfetch"]:
        out.append("read_url_content")
    if c["websearch"]:
        out.append("search_web")
    if c["delegate"]:
        out.append("invoke_subagent")
    return out


def title(name):
    return " ".join(w.capitalize() for w in name.split("-"))


def build(src, out, models):
    models = dict(MODELS, **models)
    for a in src.agents:
        if not a.for_target(NAME):
            continue
        primary = a.meta.get("role") == "primary"
        meta = OrderedDict(name=a.name, description=a.meta["description"])
        meta["tools"] = tools(a)
        meta["mainAgent"] = primary
        meta["subagent"] = not primary
        meta["inheritMcp"] = True  # Context7 is mandatory for every agent
        meta["model"] = models.get(a.meta.get("model_tier", "inherit"), "inherit")
        meta.update(a.meta.get("x-" + NAME) or {})
        body = "\n# %s\n\n%s" % (title(a.name), agent_body(a, NAME, TOOLS, LABEL, GLOSSARY).lstrip("\n"))
        out.add("agents/%s.md" % a.name, frontmatter.join(meta, body))

    for s in src.skills:
        if not s.for_target(NAME):
            continue
        text, files = plain_skill(s, NAME, TOOLS)
        out.add("skills/%s/SKILL.md" % s.name, text)
        out.add_tree("skills/%s/" % s.name, files)

    for c in src.commands:
        text, files = command_as_skill(src, c, NAME, TOOLS, LABEL, GLOSSARY)
        out.add("skills/%s/SKILL.md" % c.name, text)
        out.add_tree("skills/%s/" % c.name, files)

    p = src.package
    out.add("plugin.json", json.dumps(OrderedDict([
        ("name", p["name"]), ("displayName", p["displayName"]), ("version", src.version),
        ("description", p["description"]),
        ("suggestedPrompts", ["/start-mission add a /health endpoint that returns the service version"]),
    ]), indent=2, ensure_ascii=False))
    out.add("hooks.json", adapter_file("antigravity", "hooks.json"))
    out.add("rules/AGENTS.md", RULES)
    out.add("mcp_config.json", context7_json("antigravity"))
    out.add_tree("actionboard/hooks/", adapter_tree("common", "hooks"))
    out.add_tree("actionboard/hooks/core/", src.hooks_core)
