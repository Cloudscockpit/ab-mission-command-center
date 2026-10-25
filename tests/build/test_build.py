"""Build system: transforms, determinism, dist/ drift, and per-target schema lint."""

import json
import os
import re
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import build  # noqa: E402
from aflib import frontmatter, render  # noqa: E402
from aflib.model import Source  # noqa: E402

DIST = os.path.join(ROOT, "dist")


def read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as fh:
        return fh.read()


def walk(root, suffix):
    for dp, _, fn in os.walk(root):
        for f in fn:
            if f.endswith(suffix):
                yield os.path.join(dp, f)


class Transforms(unittest.TestCase):
    def test_frontmatter_roundtrip(self):
        text = ("---\nname: x\ndescription: \"A: quoted\"\ntargets: [claude, codex]\n"
                "capabilities:\n  read: true\n  bash: ask\nlist:\n  - a\n  - b\nn: 3\n---\nbody\n")
        meta, body = frontmatter.split(text)
        self.assertEqual(meta, {"name": "x", "description": "A: quoted", "targets": ["claude", "codex"],
                                "capabilities": {"read": True, "bash": "ask"}, "list": ["a", "b"], "n": 3})
        self.assertEqual(body, "body\n")
        self.assertEqual(frontmatter.split(frontmatter.join(meta, body)), (meta, body))

    def test_frontmatter_rejects_garbage(self):
        with self.assertRaises(ValueError):
            frontmatter.split("---\nnot a mapping line\n---\n")

    def test_conditionals(self):
        text = "a\n<!-- only:claude -->\nC\n<!-- /only -->\n<!-- not:claude -->\nN\n<!-- only:codex -->\nX\n<!-- /only -->\n<!-- /not -->\nz\n"
        self.assertEqual(render.strip_conditionals(text, "claude"), "a\nC\nz\n")
        self.assertEqual(render.strip_conditionals(text, "codex"), "a\nN\nX\nz\n")
        self.assertEqual(render.strip_conditionals(text, "opencode"), "a\nN\nz\n")
        with self.assertRaises(ValueError):
            render.strip_conditionals("<!-- only:claude -->\nx\n", "claude")

    def test_unknown_placeholder_fails(self):
        with self.assertRaises(KeyError):
            render.fill("{{tool:nope}}", {}, "t")
        self.assertEqual(render.fill("${{ vars.X }} {{a}}", {"a": "1"}), "${{ vars.X }} 1")


class Source_(unittest.TestCase):
    def test_src_is_cli_neutral(self):
        """Plan step 1.9: no CLI-specific references outside conditional blocks."""
        bad = re.compile(r"CLAUDE_PLUGIN_ROOT|`Agent` tool|`Skill` tool|/reload-plugins")
        for path in walk(os.path.join(ROOT, "src"), (".md", ".json")):
            text = render.strip_conditionals(read(path), "__none__")
            text = re.sub(r"(?s)^---\n.*?\n---\n", "", text)  # x-claude frontmatter is allowed
            self.assertIsNone(bad.search(text), path)

    def test_source_loads(self):
        src = Source()
        self.assertEqual({a.name for a in src.agents},
                         {"black-agent", "blue-agent", "green-agent", "red-agent", "sandbox-warden", "yellow-agent"})
        self.assertRegex(src.version, r"^\d+\.\d+\.\d+")


class Dist(unittest.TestCase):
    def test_dist_is_up_to_date(self):
        self.assertEqual(build.main(["--check"]), 0, "run: python scripts/build.py --target all")

    def test_build_is_deterministic(self):
        a, b = tempfile.mkdtemp(), tempfile.mkdtemp()
        build.main(["--out", a])
        build.main(["--out", b])
        for t in build.TARGETS:
            files = build.build_target(Source(), t, {})
            self.assertEqual(build.diff_tree(os.path.join(a, t), files), [])
            self.assertEqual(build.diff_tree(os.path.join(b, t), files), [])

    def test_model_config_override(self):
        files = build.build_target(Source(), "opencode", {"models": {"opencode": {"strong": "anthropic/x"}}})
        self.assertIn("\nmodel: anthropic/x\n", files["agents/black-agent.md"])
        self.assertNotIn("\nmodel:", files["agents/red-agent.md"])

    def test_versions_stamped(self):
        version = read(ROOT, "src", "VERSION").strip()
        self.assertEqual(json.loads(read(DIST, "claude", ".claude-plugin", "plugin.json"))["version"], version)
        self.assertEqual(json.loads(read(DIST, "antigravity", "plugin.json"))["version"], version)
        market = json.loads(read(ROOT, ".claude-plugin", "marketplace.json"))
        self.assertEqual(market["plugins"][0]["version"], version)
        self.assertEqual(market["plugins"][0]["source"], "./dist/claude")
        self.assertEqual(json.loads(read(DIST, "opencode", "actionboard", "config.json"))["version"], version)

    def test_no_unrendered_placeholders(self):
        for path in walk(DIST, (".md", ".json", ".toml", ".ts")):
            self.assertNotRegex(read(path), r"\{\{[a-z_]+(:[a-z_]+)?\}\}", path)


class Lint(unittest.TestCase):
    """Phase 9.3: frontmatter schema per target."""

    def skills(self, root):
        for path in walk(root, "SKILL.md"):
            meta, _ = frontmatter.split(read(path))
            yield path, meta

    def test_skill_frontmatter(self):
        roots = {"claude": os.path.join(DIST, "claude", "skills"),
                 "opencode": os.path.join(DIST, "opencode", "skills"),
                 "codex": os.path.join(DIST, "codex", ".agents", "skills"),
                 "antigravity": os.path.join(DIST, "antigravity", "skills")}
        for target, root in roots.items():
            names = set()
            for path, meta in self.skills(root):
                name = os.path.basename(os.path.dirname(path))
                names.add(name)
                self.assertEqual(meta.get("name"), name, path)
                self.assertRegex(name, r"^[a-z0-9]+(-[a-z0-9]+)*$")
                self.assertTrue(1 <= len(meta.get("description", "")) <= 1024, path)
                if target != "claude":
                    self.assertEqual(set(meta), {"name", "description"}, path)
            if target in ("codex", "antigravity"):
                self.assertIn("start-mission", names)
            self.assertEqual("browser-actions" in names, target == "claude")

    def test_opencode_agents(self):
        for path in walk(os.path.join(DIST, "opencode", "agents"), ".md"):
            meta, _ = frontmatter.split(read(path))
            self.assertIn(meta["mode"], ("primary", "subagent"))
            self.assertLessEqual(set(meta), {"description", "mode", "model", "permission"})
            for key, value in meta["permission"].items():
                values = value.values() if isinstance(value, dict) else [value]
                self.assertTrue(set(values) <= {"allow", "ask", "deny"}, (path, key))
        cmd, _ = frontmatter.split(read(DIST, "opencode", "commands", "start-mission.md"))
        self.assertEqual(cmd["agent"], "black-agent")
        for path in walk(os.path.join(DIST, "opencode", "commands"), ".md"):
            meta, _ = frontmatter.split(read(path))
            self.assertLessEqual(set(meta), {"description", "agent", "subtask"}, path)

    def test_opencode_skill_commands(self):
        """Every user-invocable skill is in the / menu, and its agent may load skills."""
        cmds = os.path.join(DIST, "opencode", "commands")
        for s in Source().skills:
            exists = os.path.exists(os.path.join(cmds, s.name + ".md"))
            wanted = s.for_target("opencode") and s.meta.get("invocation") != "model"
            self.assertEqual(exists, wanted, s.name)
            if exists:
                meta, body = frontmatter.split(read(cmds, s.name + ".md"))
                self.assertIn("`%s` skill" % s.name, body)
                agent = meta.get("agent")
                if agent:
                    ameta, _ = frontmatter.split(read(DIST, "opencode", "agents", agent + ".md"))
                    self.assertEqual(ameta["permission"]["skill"], "allow", agent)
        for name in ("mission-brief", "mission-plan", "mission-report"):
            self.assertTrue(os.path.exists(os.path.join(cmds, name + ".md")), name)

    def test_cost_and_context_rules_reach_every_target(self):
        agent_dirs = {"claude": ("claude", "agents"), "opencode": ("opencode", "agents"),
                      "antigravity": ("antigravity", "agents"), "codex": ("codex", ".codex", "agents")}
        skill_dirs = {"claude": ("claude", "skills"), "opencode": ("opencode", "skills"),
                      "antigravity": ("antigravity", "skills"), "codex": ("codex", ".agents", "skills")}
        for t, parts in agent_dirs.items():
            for path in walk(os.path.join(DIST, *parts), (".md", ".toml")):
                text = read(path)
                self.assertIn("## Operating policy (cost and accuracy)", text, path)
                self.assertIn("Never compress these.", text, path)
                self.assertIn("Files created/changed:", text, path)
            black = read(DIST, *parts, "black-agent.md") if t != "codex" else \
                read(DIST, "codex", ".agents", "skills", "start-mission", "references", "black-agent.md")
            self.assertIn("Step 0 — Preflight", black, t)
            skills = os.path.join(DIST, *skill_dirs[t])
            for doc in ("mission-brief", "mission-plan", "mission-report"):
                self.assertIn("**Full prose, always.**", read(skills, doc, "SKILL.md"), (t, doc))
            for f in ("SKILL.md", "LICENSE.txt", "NOTICE.txt"):
                self.assertTrue(os.path.exists(os.path.join(skills, "terse-output", f)), (t, f))
            self.assertTrue(os.path.exists(os.path.join(skills, "mission-preflight", "SKILL.md")), t)

    def test_maturity_summary_reaches_every_target(self):
        skill_dirs = {"claude": ("claude", "skills"), "opencode": ("opencode", "skills"),
                      "antigravity": ("antigravity", "skills"), "codex": ("codex", ".agents", "skills")}
        for t, parts in skill_dirs.items():
            skills = os.path.join(DIST, *parts)
            report = read(skills, "mission-report", "SKILL.md")
            self.assertIn("## Maturity & Progress Summary", report, t)
            self.assertIn("actionboard-devops-mission/scripts/maturity.py", report, t)
            self.assertTrue(os.path.exists(os.path.join(
                skills, "actionboard-devops-mission", "scripts", "maturity.py")), t)
            self.assertIn("## Maturity & Progress Summary", read(
                skills, "actionboard-devops-mission", "assets", "mission-report-template.md"), t)

    def test_context7_configured_for_every_target(self):
        url = "https://mcp.context7.com/mcp"
        self.assertEqual(json.loads(read(DIST, "claude", ".mcp.json"))["mcpServers"]["context7"],
                         {"type": "http", "url": url})
        self.assertEqual(json.loads(read(DIST, "antigravity", "mcp_config.json"))["mcpServers"]["context7"],
                         {"url": url})
        self.assertEqual(json.loads(read(DIST, "opencode", "actionboard", "mcp.json"))["mcp"]["context7"]["url"], url)
        self.assertIn('url = "%s"' % url, read(DIST, "codex", ".codex", "actionboard", "mcp.toml"))

    def test_codex_agents(self):
        try:
            import tomllib
        except ImportError:
            self.skipTest("tomllib needs Python 3.11+")
        for path in walk(os.path.join(DIST, "codex", ".codex", "agents"), ".toml"):
            with open(path, "rb") as fh:
                data = tomllib.load(fh)
            self.assertTrue({"name", "description", "developer_instructions"} <= set(data), path)
            self.assertNotIn("sandbox_mode", data)
        self.assertFalse(os.path.exists(os.path.join(DIST, "codex", ".codex", "agents", "black-agent.toml")))

    def test_antigravity_agents(self):
        known = {"view_file", "list_dir", "find_by_name", "grep_search", "write_to_file",
                 "replace_file_content", "multi_replace_file_content", "run_command",
                 "read_url_content", "search_web", "invoke_subagent"}
        for path in walk(os.path.join(DIST, "antigravity", "agents"), ".md"):
            meta, body = frontmatter.split(read(path))
            self.assertTrue(set(meta["tools"]) <= known, path)
            self.assertIn(meta["model"], ("inherit", "flash", "pro"))
            self.assertTrue(body.lstrip("\n").startswith("# "), path)

    def test_claude_agents(self):
        allowed = {"Read", "Write", "Edit", "Bash", "Glob", "Grep", "WebFetch", "WebSearch", "Agent", "Skill"}
        for path in walk(os.path.join(DIST, "claude", "agents"), ".md"):
            meta, _ = frontmatter.split(read(path))
            self.assertTrue(set(meta["tools"].split(", ")) <= allowed, path)
            self.assertIn(meta["model"], ("opus", "sonnet", "inherit"))


if __name__ == "__main__":
    unittest.main()
