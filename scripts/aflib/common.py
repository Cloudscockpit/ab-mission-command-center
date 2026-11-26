"""Helpers shared by the non-Claude adapters."""

from collections import OrderedDict

import json

from . import frontmatter
from .model import glossary_section, render_text, render_tree

# Mandatory for every target: the hosted Context7 MCP server (Streamable HTTP, no
# Node needed). An optional CONTEXT7_API_KEY raises its rate limits.
CONTEXT7_URL = "https://mcp.context7.com/mcp"

# The ActionBoard MCP server (packages/actionboard-mcp): login, Pods/Boards, fetch and submit missions.
# Every target's MCP config runs `uvx --from ACTIONBOARD_MCP_SOURCE actionboard-mcp`, so users need uv,
# not a clone; the server works in the client's project folder. Pin it here, in one place: a release tag
# ("git+https://github.com/Cloudscockpit/ab-mission-command-center@v1.4.0#subdirectory=packages/actionboard-mcp")
# or PyPI ("actionboard-mcp==0.1.0").
ACTIONBOARD_MCP_SOURCE = "git+https://github.com/Cloudscockpit/ab-mission-command-center#subdirectory=packages/actionboard-mcp"
ACTIONBOARD_MCP_ARGS = ["--from", ACTIONBOARD_MCP_SOURCE, "actionboard-mcp"]
MCP_SERVERS = ("context7", "actionboard")


def mcp_json(shape):
    """Context7 and ActionBoard MCP config in each CLI's JSON shape."""
    if shape == "claude":
        servers = {"context7": OrderedDict([("type", "http"), ("url", CONTEXT7_URL)]),
                   "actionboard": OrderedDict([("command", "uvx"), ("args", ACTIONBOARD_MCP_ARGS)])}
        return json.dumps({"mcpServers": servers}, indent=2)
    if shape == "antigravity":
        servers = {"context7": {"url": CONTEXT7_URL},
                   "actionboard": OrderedDict([("command", "uvx"), ("args", ACTIONBOARD_MCP_ARGS)])}
        return json.dumps({"mcpServers": servers}, indent=2)
    if shape == "opencode":
        servers = {"context7": OrderedDict([("type", "remote"), ("url", CONTEXT7_URL), ("enabled", True)]),
                   "actionboard": OrderedDict([("type", "local"), ("command", ["uvx"] + ACTIONBOARD_MCP_ARGS),
                                               ("enabled", True)])}
        return json.dumps({"mcp": servers}, indent=2)
    raise ValueError(shape)


def mcp_toml():
    # ab_login waits up to 5 minutes for the browser sign-in; the first uvx run downloads the server.
    return ('[mcp_servers.context7]\nurl = "%s"\n\n'
            '[mcp_servers.actionboard]\ncommand = "uvx"\nargs = %s\n'
            'startup_timeout_sec = 120\ntool_timeout_sec = 330\n'
            % (CONTEXT7_URL, json.dumps(ACTIONBOARD_MCP_ARGS)))

ARGS_TEXT = "the objective the user typed after the skill name"


def skill_values(tools, skill_dir, skills_root, args="<arguments>"):
    v = {"tool:" + k: t for k, t in tools.items()}
    v.update(skill_dir=skill_dir, skills_root=skills_root, args=args)
    return v


def skill_note(args=None):
    note = ("> Paths written `<skill-dir>/...` are relative to the directory that contains "
            "this SKILL.md.")
    if args:
        note += " `%s` means what the user asked for when invoking this skill." % args
    return note + "\n\n"


def plain_skill(skill, target, tools, extra_meta=None):
    """Render a skill with only name/description frontmatter (Agent Skills spec)."""
    meta = OrderedDict(name=skill.name, description=skill.meta["description"])
    meta.update(extra_meta or {})
    vals = skill_values(tools, "<skill-dir>", "<skill-dir>/..")
    body = render_text(skill.body, target, vals, "skills/" + skill.name)
    if "<skill-dir>" in body or "<arguments>" in body:
        body = "\n" + skill_note("<arguments>" if "<arguments>" in body else None) + body.lstrip("\n")
    files = render_tree(skill.files, target, vals, "skills/" + skill.name)
    return frontmatter.join(meta, body), files


def agent_body(agent, target, tools, label, glossary):
    vals = skill_values(tools, "<skill-dir>", "<skill-dir>/..")
    body = render_text(agent.body, target, vals, "agents/" + agent.name)
    return body.rstrip("\n") + "\n" + glossary_section(label, glossary, agent)


def command_as_skill(src, command, target, tools, label, glossary):
    """For CLIs without custom commands: the command becomes a skill whose
    session plays the command's primary agent, with that agent's prompt bundled
    as references/<agent>.md."""
    meta = OrderedDict(name=command.name, description=command.meta["description"])
    vals = skill_values(tools, "<skill-dir>", "<skill-dir>/..", args=ARGS_TEXT)
    body = render_text(command.body, target, vals, "commands/" + command.name)
    body = body.replace("**%s**" % ARGS_TEXT, "the text the user typed after `%s` (ask for it if "
                        "they gave none)" % command.name)
    body = "\n" + skill_note() + body.lstrip("\n")
    files = OrderedDict()
    lead = command.meta.get("agent")
    if lead:
        files["references/%s.md" % lead] = agent_body(src.agent(lead), target, tools, label, glossary)
    return frontmatter.join(meta, body), files
