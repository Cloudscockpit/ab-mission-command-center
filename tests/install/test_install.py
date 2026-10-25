"""Install/uninstall round trip into a throwaway project for every file-based target."""

import contextlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import install  # noqa: E402

USER_HOOKS = {"hooks": {"PreToolUse": [{"matcher": "x", "hooks": [{"type": "command", "command": "echo mine"}]}]}}


def run(*args):
    with contextlib.redirect_stdout(io.StringIO()) as out:
        code = install.main(list(args))
    return code, out.getvalue()


def snapshot(root):
    out = {}
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d != ".git"]
        for f in fn:
            with open(os.path.join(dp, f), "rb") as fh:
                out[os.path.relpath(os.path.join(dp, f), root)] = fh.read()
        if not fn and not dn and dp != root:
            out[os.path.relpath(dp, root) + os.sep] = b""
    return out


class RoundTrip(unittest.TestCase):
    def setUp(self):
        self.project = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.project, ".codex"))
        with open(os.path.join(self.project, "AGENTS.md"), "w", encoding="utf-8") as fh:
            fh.write("# existing\n")
        with open(os.path.join(self.project, ".codex", "hooks.json"), "w", encoding="utf-8") as fh:
            json.dump(USER_HOOKS, fh)
        self.before = snapshot(self.project)

    def tearDown(self):
        shutil.rmtree(self.project, ignore_errors=True)

    def hooks(self):
        with open(os.path.join(self.project, ".codex", "hooks.json"), encoding="utf-8") as fh:
            return json.load(fh)["hooks"]

    def test_install_twice_then_uninstall_restores_project(self):
        for _ in range(2):  # reinstall must be idempotent
            for t in ("opencode", "codex", "antigravity"):
                self.assertEqual(run("--target", t, "--project", self.project)[0], 0, t)
        pre = self.hooks()["PreToolUse"]
        self.assertEqual(len(pre), 2)
        self.assertNotRegex(json.dumps(pre), r"__[A-Z_]+__")
        with open(os.path.join(self.project, "AGENTS.md"), encoding="utf-8") as fh:
            self.assertEqual(fh.read().count("actionboard:begin"), 1)
        for rel in (".opencode/agents/black-agent.md", ".opencode/plugins/actionboard-guard.ts",
                    ".agents/skills/start-mission/SKILL.md", ".codex/agents/red-agent.toml",
                    ".codex/rules/actionboard.rules",
                    ".agents/plugins/actionboard-v5-agentformation/plugin.json"):
            self.assertTrue(os.path.exists(os.path.join(self.project, rel)), rel)
        with open(os.path.join(self.project, ".agents/plugins/actionboard-v5-agentformation/hooks.json"),
                  encoding="utf-8") as fh:
            self.assertNotRegex(fh.read(), r"__[A-Z_]+__")

        for t in ("opencode", "codex", "antigravity"):
            self.assertEqual(run("--target", t, "--project", self.project, "--uninstall")[0], 0, t)
        after = snapshot(self.project)
        self.assertEqual(sorted(after), sorted(self.before))
        self.assertEqual(self.hooks(), USER_HOOKS["hooks"])
        self.assertEqual(after["AGENTS.md"].replace(b"\r\n", b"\n"), b"# existing\n")

    def test_refuses_to_overwrite_foreign_files(self):
        path = os.path.join(self.project, ".opencode", "agents", "red-agent.md")
        os.makedirs(os.path.dirname(path))
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("mine")
        code, out = run("--target", "opencode", "--project", self.project)
        self.assertEqual(code, 1)
        self.assertIn("Refusing to overwrite", out)
        with open(path, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "mine")

    def test_uninstall_keeps_modified_files(self):
        run("--target", "opencode", "--project", self.project)
        path = os.path.join(self.project, ".opencode", "agents", "red-agent.md")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("\nlocal tweak\n")
        code, out = run("--target", "opencode", "--project", self.project, "--uninstall")
        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists(path))
        self.assertIn("kept (modified since install)", out)

    def test_context7_added_and_removed(self):
        self.assertEqual(run("--target", "opencode", "--project", self.project)[0], 0)
        self.assertEqual(run("--target", "codex", "--project", self.project)[0], 0)
        with open(os.path.join(self.project, "opencode.json"), encoding="utf-8") as fh:
            server = json.load(fh)["mcp"]["context7"]
        self.assertEqual(server, {"type": "remote", "url": "https://mcp.context7.com/mcp", "enabled": True})
        with open(os.path.join(self.project, ".codex", "config.toml"), encoding="utf-8") as fh:
            self.assertIn('[mcp_servers.context7]\nurl = "https://mcp.context7.com/mcp"', fh.read())
        for t in ("opencode", "codex"):
            run("--target", t, "--project", self.project, "--uninstall")
        self.assertFalse(os.path.exists(os.path.join(self.project, "opencode.json")))
        self.assertFalse(os.path.exists(os.path.join(self.project, ".codex", "config.toml")))

    def test_user_context7_is_never_touched(self):
        mine_json = {"mcp": {"context7": {"type": "local", "command": ["my-context7"]}}, "theme": "x"}
        mine_toml = '# mine\n[mcp_servers.context7]\ncommand = "my-context7"\n'
        with open(os.path.join(self.project, "opencode.json"), "w", encoding="utf-8") as fh:
            json.dump(mine_json, fh)
        with open(os.path.join(self.project, ".codex", "config.toml"), "w", encoding="utf-8") as fh:
            fh.write(mine_toml)
        for t in ("opencode", "codex"):
            self.assertEqual(run("--target", t, "--project", self.project)[0], 0)
            run("--target", t, "--project", self.project, "--uninstall")
        with open(os.path.join(self.project, "opencode.json"), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), mine_json)
        with open(os.path.join(self.project, ".codex", "config.toml"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), mine_toml)

    def test_codex_config_keeps_user_settings(self):
        path = os.path.join(self.project, ".codex", "config.toml")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write('model = "gpt-x"\n')
        run("--target", "codex", "--project", self.project)
        run("--target", "codex", "--project", self.project)  # idempotent
        with open(path, encoding="utf-8") as fh:
            self.assertEqual(fh.read().count("[mcp_servers.context7]"), 1)
        run("--target", "codex", "--project", self.project, "--uninstall")
        with open(path, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), 'model = "gpt-x"\n')

    def prefs(self):
        with open(os.path.join(self.project, ".actionboard", "preferences.json"), encoding="utf-8") as fh:
            return json.load(fh)

    def test_opt_in_flags_record_preferences(self):
        installed = []
        original = install.install_graphify
        install.install_graphify = lambda dry: installed.append(dry) or True
        try:
            run("--target", "opencode", "--project", self.project, "--with", "graphify,terse")
        finally:
            install.install_graphify = original
        self.assertEqual(installed, [False])
        self.assertEqual(self.prefs(), {"graphify": "enabled", "terse_output": "enabled"})
        run("--target", "opencode", "--project", self.project, "--without", "terse")
        self.assertEqual(self.prefs(), {"graphify": "enabled", "terse_output": "declined"})

    def test_no_flags_and_no_tty_leaves_choice_to_preflight(self):
        run("--target", "opencode", "--project", self.project, "--yes")
        self.assertFalse(os.path.exists(os.path.join(self.project, ".actionboard")))
        with self.assertRaises(SystemExit):
            install.main(["--target", "opencode", "--project", self.project, "--with", "nope"])

    def test_dry_run_writes_nothing(self):
        run("--target", "codex", "--project", self.project, "--dry-run")
        self.assertEqual(snapshot(self.project), self.before)


# ------------------------------------------------------------------ --cleanup

ORIGIN = "https://github.com/Cloudscockpit/ab-mission-command-center.git"
CLONE_DIRS = ("scripts", "dist", "src", "adapters")
UNINSTALLERS = {
    "codex": os.path.join(".codex", "actionboard", "actionboard_uninstall.py"),
    "opencode": os.path.join(".opencode", "actionboard", "actionboard_uninstall.py"),
    "antigravity": os.path.join(".agents", "plugins", "actionboard-v5-agentformation",
                                "actionboard_uninstall.py"),
}


def git(cwd, *args):
    cmd = ["git", "-c", "user.name=ab-test", "-c", "user.email=ab-test@example.invalid",
           "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false"] + list(args)
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=True)


def tracked_files():
    """Files of this working tree (tracked + new, minus ignored) a checkout needs to run."""
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"],
                         cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [f for f in out.splitlines()
            if (f.split("/")[0] in CLONE_DIRS or f == ".gitignore")
            and os.path.isfile(os.path.join(ROOT, f))]


def make_repo(path, origin=ORIGIN, files=None):
    """A committed, clean git work tree at path with the given origin.
    files=None makes a one-file toy repo; otherwise the listed files are copied from ROOT."""
    os.makedirs(path)
    for rel in files if files is not None else ["README.md"]:
        dest = os.path.join(path, *rel.split("/"))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if files is None:
            with open(dest, "w", encoding="utf-8") as fh:
                fh.write("x\n")
        else:
            shutil.copyfile(os.path.join(ROOT, *rel.split("/")), dest)
    git(path, "init", "-q")
    if origin:
        git(path, "remote", "add", "origin", origin)
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "clone")
    if origin:  # a real clone has a remote-tracking ref; without it every commit counts as unpushed
        git(path, "update-ref", "refs/remotes/origin/main", "HEAD")
    return path


def make_link(link, target):
    """Symlink (junction on Windows without symlink rights). False when neither works."""
    try:
        os.symlink(target, link, target_is_directory=True)
        return True
    except (OSError, NotImplementedError):
        pass
    if os.name == "nt":
        return subprocess.run(["cmd", "/c", "mklink", "/J", link, target],
                              capture_output=True).returncode == 0
    return False


def run_script(script, *args, cwd=None, isolated=False):
    cmd = [sys.executable] + (["-I"] if isolated else []) + [script] + list(args)
    env = dict(os.environ, ACTIONBOARD_OPENCODE_MAJOR="2")
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=300)


class CleanupBase(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.project = os.path.join(self.tmp, "proj")
        os.makedirs(self.project)

    def tearDown(self):
        os.chdir(ROOT)
        shutil.rmtree(self.tmp, onerror=lambda f, p, e: (os.chmod(p, stat.S_IWRITE), f(p)))


class ZeroLeftoverClone(CleanupBase):
    """The one-liner flow: clone inside the project, install with --cleanup, no clone left."""

    def seed(self):
        os.makedirs(os.path.join(self.project, ".codex"))
        with open(os.path.join(self.project, "AGENTS.md"), "w", encoding="utf-8") as fh:
            fh.write("# existing\n")
        with open(os.path.join(self.project, ".codex", "hooks.json"), "w", encoding="utf-8") as fh:
            json.dump(USER_HOOKS, fh)
        return snapshot(self.project)

    def check_target(self, target):
        before = self.seed()
        clone = make_repo(os.path.join(self.project, "ab-mission-command-center"), files=tracked_files())
        r = run_script(os.path.join(clone, "scripts", "install.py"), "--target", target,
                       "--project", self.project, "--cleanup", "--yes", cwd=self.project)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("removed ", r.stdout)
        self.assertFalse(os.path.exists(clone), "clone must be gone")
        uninstaller = os.path.join(self.project, UNINSTALLERS[target])
        self.assertTrue(os.path.isfile(uninstaller), "standalone uninstaller must be installed")
        # Installed files must not point back into the deleted clone.
        needle = clone.replace("\\", "/").encode()
        for dp, _, fn in os.walk(self.project):
            for f in fn:
                with open(os.path.join(dp, f), "rb") as fh:
                    self.assertNotIn(needle, fh.read().replace(b"\\", b"/"), os.path.join(dp, f))
        # No clone, no build step: the copied uninstaller (isolated, no sibling imports) restores the project.
        u = run_script(uninstaller, isolated=True, cwd=self.tmp)
        self.assertEqual(u.returncode, 0, u.stdout + u.stderr)
        self.assertEqual(sorted(snapshot(self.project)), sorted(before))
        self.assertEqual(snapshot(self.project)["AGENTS.md"].replace(b"\r\n", b"\n"), b"# existing\n")

    def test_codex(self):
        self.check_target("codex")

    def test_antigravity(self):
        self.check_target("antigravity")

    def test_opencode(self):
        self.check_target("opencode")

    def test_refusal_subprocess_deletes_nothing(self):
        clone = make_repo(os.path.join(self.project, "ab-mission-command-center"), files=tracked_files())
        stray = os.path.join(clone, "my-notes.txt")
        with open(stray, "w", encoding="utf-8") as fh:
            fh.write("precious")
        r = run_script(os.path.join(clone, "scripts", "install.py"), "--target", "opencode",
                       "--project", self.project, "--cleanup", "--yes", cwd=self.project)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("--cleanup skipped, checkout left in place", r.stdout)
        self.assertTrue(os.path.isfile(stray))
        self.assertTrue(os.path.isdir(os.path.join(self.project, ".opencode")), "install itself still succeeded")


class CleanupRefusals(CleanupBase):
    def setUp(self):
        super().setUp()
        self.repo = make_repo(os.path.join(self.project, "ab-mission-command-center"))

    def refusal(self, project=None, config=None, scope="project", repo=None):
        return install.cleanup_refusal(repo or self.repo, project or self.project, config, scope)

    def assertRefused(self, fragment, **kw):
        reason = self.refusal(**kw)
        self.assertIsNotNone(reason)
        self.assertIn(fragment, reason)
        # cleanup() itself must not call the remover when refused
        remover = mock.Mock()
        repo = kw.get("repo") or self.repo
        with contextlib.redirect_stdout(io.StringIO()) as out:
            done = install.cleanup(repo, kw.get("project") or self.project,
                                   kw.get("config"), kw.get("scope", "project"), remove=remover)
        self.assertFalse(done)
        remover.assert_not_called()
        self.assertIn("--cleanup skipped, checkout left in place", out.getvalue())
        self.assertTrue(os.path.isdir(repo))

    def test_clean_checkout_is_allowed(self):
        self.assertIsNone(self.refusal())

    def test_dirty_tree_untracked(self):
        with open(os.path.join(self.repo, "untracked.txt"), "w", encoding="utf-8") as fh:
            fh.write("x")
        self.assertRefused("uncommitted or untracked")

    def test_dirty_tree_modified(self):
        with open(os.path.join(self.repo, "README.md"), "a", encoding="utf-8") as fh:
            fh.write("edit\n")
        self.assertRefused("uncommitted or untracked")

    def test_unpushed_commit(self):
        with open(os.path.join(self.repo, "README.md"), "a", encoding="utf-8") as fh:
            fh.write("local work\n")
        git(self.repo, "commit", "-q", "-am", "local")
        self.assertRefused("unpushed commits")

    def test_pushed_follow_up_commit_is_allowed(self):
        with open(os.path.join(self.repo, "README.md"), "a", encoding="utf-8") as fh:
            fh.write("more\n")
        git(self.repo, "commit", "-q", "-am", "more")
        git(self.repo, "update-ref", "refs/remotes/origin/main", "HEAD")
        self.assertIsNone(self.refusal())

    def test_repo_without_any_remote_ref_is_refused(self):
        git(self.repo, "update-ref", "-d", "refs/remotes/origin/main")
        self.assertRefused("unpushed commits")

    def test_stash_entry(self):
        with open(os.path.join(self.repo, "README.md"), "a", encoding="utf-8") as fh:
            fh.write("wip\n")
        git(self.repo, "stash", "push", "-q")
        self.assertRefused("stash entries")

    def test_ignored_non_pyc_file(self):
        with open(os.path.join(self.repo, ".gitignore"), "w", encoding="utf-8") as fh:
            fh.write(".env\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "ignore")
        git(self.repo, "update-ref", "refs/remotes/origin/main", "HEAD")
        self.assertIsNone(self.refusal())
        with open(os.path.join(self.repo, ".env"), "w", encoding="utf-8") as fh:
            fh.write("SECRET=1\n")
        self.assertRefused("ignored files present")
        self.assertTrue(os.path.isfile(os.path.join(self.repo, ".env")))

    def test_ignored_pycache_does_not_block(self):
        with open(os.path.join(self.repo, ".gitignore"), "w", encoding="utf-8") as fh:
            fh.write("__pycache__/\n*.pyc\n")
        os.makedirs(os.path.join(self.repo, "scripts"))  # tracked dir, as in a real clone
        with open(os.path.join(self.repo, "scripts", "keep.py"), "w", encoding="utf-8") as fh:
            fh.write("x = 1\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "ignore")
        git(self.repo, "update-ref", "refs/remotes/origin/main", "HEAD")
        for rel in ("scripts/__pycache__/x.cpython-314.pyc", "__pycache__/y.pyc"):
            path = os.path.join(self.repo, *rel.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(b"\0")
        self.assertIsNone(self.refusal())

    def test_foreign_origin(self):
        for url in ("https://github.com/evil/ab-mission-command-center.git",
                    "https://github.com/Cloudscockpit/ab-mission-command-center-evil.git",
                    "https://github.com/Cloudscockpit/ab-mission-command-center/extra",
                    "https://evil.example/github.com/Cloudscockpit/ab-mission-command-center.git",
                    "https://github.com.evil.example/Cloudscockpit/ab-mission-command-center.git",
                    "http://github.com/Cloudscockpit/ab-mission-command-center.git",
                    "file:///x/Cloudscockpit/ab-mission-command-center"):
            git(self.repo, "remote", "set-url", "origin", url)
            reason = self.refusal()
            self.assertIsNotNone(reason, url)
            self.assertIn("origin", reason, url)

    def test_missing_origin(self):
        git(self.repo, "remote", "remove", "origin")
        self.assertRefused("origin")

    def test_accepted_origins(self):
        for url in (ORIGIN, "https://github.com/Cloudscockpit/ab-mission-command-center",
                    "https://github.com/cloudscockpit/AB-Mission-Command-Center.git",
                    "git@github.com:Cloudscockpit/ab-mission-command-center.git",
                    "ssh://git@github.com/Cloudscockpit/ab-mission-command-center.git",
                    "https://user@github.com/Cloudscockpit/ab-mission-command-center.git"):
            git(self.repo, "remote", "set-url", "origin", url)
            self.assertIsNone(self.refusal(), url)

    def test_project_is_the_clone(self):
        self.assertRefused("not a subdirectory", project=self.repo)

    def test_clone_contains_project(self):
        inner = os.path.join(self.repo, "sub", "proj")
        os.makedirs(inner)
        self.assertRefused("not a subdirectory", project=inner)

    def test_clone_is_not_under_project(self):
        other = os.path.join(self.tmp, "elsewhere")
        os.makedirs(other)
        self.assertRefused("not a subdirectory", project=other)

    def test_sibling_prefix_is_not_a_subdirectory(self):
        # proj-evil must not count as inside proj
        evil = make_repo(os.path.join(self.tmp, "proj-evil"))
        self.assertRefused("not a subdirectory", repo=evil)

    def test_project_symlinked_into_clone(self):
        os.makedirs(os.path.join(self.repo, "sub"))
        link = os.path.join(self.tmp, "link")
        if not make_link(link, os.path.join(self.repo, "sub")):
            self.skipTest("cannot create a symlink or junction here")
        self.assertRefused("not a subdirectory", project=link)

    def test_project_symlinked_to_clone_itself(self):
        link = os.path.join(self.tmp, "viaLink")
        if not make_link(link, self.repo):
            self.skipTest("cannot create a symlink or junction here")
        self.assertRefused("not a subdirectory", project=link)

    @unittest.skipUnless(os.name == "nt", "Windows paths are case-insensitive")
    def test_windows_case_insensitive_paths(self):
        self.assertIsNone(self.refusal(project=self.project.swapcase()))
        self.assertRefused("not a subdirectory", project=self.repo.swapcase())

    def test_config_inside_clone(self):
        self.assertRefused("--config", config=os.path.join(self.repo, "agentformation.config.json"))
        self.assertRefused("--config", config=self.repo)

    def test_config_outside_clone_allowed(self):
        self.assertIsNone(self.refusal(config=os.path.join(self.project, "agentformation.config.json")))

    def test_git_missing(self):
        with mock.patch.object(install.shutil, "which", return_value=None):
            self.assertRefused("git is not available")

    def test_not_a_git_checkout(self):
        plain = os.path.join(self.project, "plain")
        os.makedirs(plain)
        self.assertRefused("not a git checkout", repo=plain)

    def test_global_scope_uses_cwd(self):
        os.chdir(self.project)
        self.assertIsNone(self.refusal(scope="global", project=os.path.join(self.tmp, "ignored")))
        deeper = os.path.join(self.repo, "deeper")
        os.makedirs(deeper)
        os.chdir(deeper)  # cwd inside the clone: clone is not below cwd
        self.assertRefused("not a subdirectory", scope="global")

    def test_cleanup_calls_remover_once_with_real_path(self):
        remover = mock.Mock()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(install.cleanup(self.repo, self.project, None, "project", remove=remover))
        remover.assert_called_once_with(os.path.realpath(self.repo))

    def test_cleanup_never_raises(self):
        remover = mock.Mock(side_effect=PermissionError("locked"))
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertFalse(install.cleanup(self.repo, self.project, None, "project", remove=remover))
        self.assertIn("could not remove", out.getvalue())
        self.assertTrue(os.path.isdir(self.repo))

    def test_cleanup_leaves_cwd_when_inside_clone(self):
        os.chdir(self.repo)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(install.cleanup(self.repo, self.project, None, "project"))
        self.assertFalse(os.path.exists(self.repo))
        self.assertEqual(os.path.realpath(os.getcwd()), os.path.realpath(os.path.dirname(self.repo)))

    def test_real_remover_does_not_follow_links_out_of_the_clone(self):
        victim = os.path.join(self.tmp, "victim")
        os.makedirs(victim)
        with open(os.path.join(victim, "keep.txt"), "w", encoding="utf-8") as fh:
            fh.write("keep")
        if not make_link(os.path.join(self.repo, "escape"), victim):
            self.skipTest("cannot create a symlink or junction here")
        with mock.patch.object(install, "cleanup_refusal", return_value=None):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertTrue(install.cleanup(self.repo, self.project, None, "project"))
        self.assertFalse(os.path.exists(self.repo))
        self.assertTrue(os.path.isfile(os.path.join(victim, "keep.txt")))


class RemoveTree(CleanupBase):
    def test_removes_tree_with_read_only_files(self):
        tree = os.path.join(self.tmp, "ro")
        os.makedirs(os.path.join(tree, ".git", "objects", "ab"))
        for rel in ("a.txt", ".git/objects/ab/cdef", ".git/HEAD"):
            path = os.path.join(tree, *rel.split("/"))
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("x")
            os.chmod(path, stat.S_IREAD)
        install.remove_tree(tree)
        self.assertFalse(os.path.exists(tree))

    def test_removes_real_git_checkout(self):
        repo = make_repo(os.path.join(self.tmp, "co"))  # git objects are read-only
        install.remove_tree(repo)
        self.assertFalse(os.path.exists(repo))


class WithoutCleanupUnchanged(CleanupBase):
    def test_real_repo_survives_cleanup_calls(self):
        # The real checkout is not under the temp project, so every route must refuse;
        # the remover is booby-trapped in case one does not.
        boom = mock.Mock(side_effect=AssertionError("tried to delete the real checkout"))
        with mock.patch.object(install, "remove_tree", boom):
            code, out = run("--target", "opencode", "--project", self.project, "--cleanup", "--yes")
        self.assertEqual(code, 0)
        self.assertIn("--cleanup skipped, checkout left in place", out)
        boom.assert_not_called()
        self.assertTrue(os.path.isfile(os.path.join(ROOT, "scripts", "install.py")))
        self.assertTrue(os.path.isdir(os.path.join(ROOT, "dist")))

    def test_dry_run_and_uninstall_never_clean_up(self):
        with mock.patch.object(install, "cleanup", side_effect=AssertionError("cleanup ran")):
            self.assertEqual(run("--target", "opencode", "--project", self.project, "--dry-run", "--cleanup")[0], 0)
            self.assertEqual(run("--target", "opencode", "--project", self.project)[0], 0)
            self.assertEqual(run("--target", "opencode", "--project", self.project, "--uninstall", "--cleanup")[0], 0)

    def test_failed_install_never_cleans_up(self):
        os.makedirs(os.path.join(self.project, ".opencode", "agents"))
        with open(os.path.join(self.project, ".opencode", "agents", "red-agent.md"), "w", encoding="utf-8") as fh:
            fh.write("mine")
        with mock.patch.object(install, "cleanup", side_effect=AssertionError("cleanup ran")):
            self.assertEqual(run("--target", "opencode", "--project", self.project, "--cleanup")[0], 1)

    def test_claude_output_unchanged_without_cleanup(self):
        code, out = run("--target", "claude", "--project", self.project, "--yes")
        self.assertEqual(code, 0)
        self.assertEqual(out, "Claude Code installs from its plugin marketplace. In Claude Code, run:\n"
                              "  /plugin marketplace add %s\n"
                              "  /plugin install actionboard-v5-agentformation@actionboard-v5-agentformation\n"
                         % install.REPO.replace("\\", "/"))

    def test_claude_with_cleanup_names_github_repo_and_deletes_nothing(self):
        with mock.patch.object(install, "remove_tree", side_effect=AssertionError("deleted")):
            code, out = run("--target", "claude", "--project", self.project, "--cleanup", "--yes")
        self.assertEqual(code, 0)
        self.assertIn("/plugin marketplace add Cloudscockpit/ab-mission-command-center\n", out)
        self.assertIn("checkout left in place", out)
        self.assertTrue(os.path.isdir(ROOT))


class StandaloneUninstaller(CleanupBase):
    def test_works_from_a_lone_copy_without_importing_build(self):
        self.assertEqual(run("--target", "codex", "--project", self.project)[0], 0)
        self.assertEqual(run("--target", "antigravity", "--project", self.project)[0], 0)
        lone = os.path.join(self.tmp, "lone")  # no scripts/ siblings at all
        os.makedirs(lone)
        copy = os.path.join(lone, "actionboard_uninstall.py")
        shutil.copyfile(os.path.join(self.project, UNINSTALLERS["codex"]), copy)
        probe = ("import runpy, sys\n"
                 "script, project = sys.argv[1], sys.argv[2]\n"
                 "sys.argv = [script, '--target', 'codex', '--project', project]\n"
                 "try:\n    runpy.run_path(script, run_name='__main__')\n"
                 "except SystemExit as e:\n    code = e.code\n"
                 "else:\n    code = 0\n"
                 "bad = [m for m in ('build', 'install', 'aflib') if m in sys.modules]\n"
                 "print('IMPORTED', bad)\n"
                 "sys.exit(code or (3 if bad else 0))\n")
        r = subprocess.run([sys.executable, "-I", "-c", probe, copy, self.project],
                           capture_output=True, text=True, cwd=lone)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("IMPORTED []", r.stdout)
        self.assertFalse(os.path.exists(os.path.join(self.project, ".codex", "actionboard", "actionboard-install.json")))
        self.assertTrue(os.path.exists(os.path.join(self.project, UNINSTALLERS["antigravity"])),
                        "other targets untouched")

    def test_no_arguments_and_no_manifest_is_a_clear_error(self):
        lone = os.path.join(self.tmp, "lone2")
        os.makedirs(lone)
        copy = os.path.join(lone, "actionboard_uninstall.py")
        shutil.copyfile(os.path.join(ROOT, "scripts", "actionboard_uninstall.py"), copy)
        r = subprocess.run([sys.executable, "-I", copy], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no manifest next to this script", r.stderr)

    def test_source_has_no_local_imports(self):
        with open(os.path.join(ROOT, "scripts", "actionboard_uninstall.py"), encoding="utf-8") as fh:
            src = fh.read()
        for banned in ("import build", "from build", "aflib", "import install"):
            self.assertNotIn(banned, src)

    def test_manifest_records_project_and_uninstaller(self):
        self.assertEqual(run("--target", "codex", "--project", self.project)[0], 0)
        path = os.path.join(self.project, ".codex", "actionboard", "actionboard-install.json")
        with open(path, encoding="utf-8") as fh:
            record = json.load(fh)
        self.assertEqual(record["project"], os.path.abspath(self.project))
        self.assertIn(os.path.join(self.project, UNINSTALLERS["codex"]), record["files"])


class PycacheOnUninstall(CleanupBase):
    """Regression (D1): pyc files Python wrote beside the installed hooks must not survive an uninstall."""

    TARGETS = ("opencode", "antigravity")

    def install(self, target):
        before = snapshot(self.project)
        self.assertEqual(run("--target", target, "--project", self.project)[0], 0)
        script = os.path.join(self.project, UNINSTALLERS[target])
        with open(script.replace("actionboard_uninstall.py", "actionboard-install.json"), encoding="utf-8") as fh:
            record = json.load(fh)
        pys = sorted(p for p in record["files"] if p.endswith(".py") and not p.endswith("actionboard_uninstall.py"))
        self.assertTrue(pys)
        override = os.environ.get("AB_TEST_UNINSTALLER_OVERRIDE")  # proof-of-fail hook: swap in an older uninstaller
        if override:
            shutil.copyfile(override, script)
        return before, script, pys

    def compile(self, pys):
        for p in pys:
            r = subprocess.run([sys.executable, "-m", "py_compile", p], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
        caches = {os.path.join(os.path.dirname(p), "__pycache__") for p in pys}
        for c in caches:
            self.assertTrue(os.path.isdir(c) and os.listdir(c), c)
        return caches

    def uninstall(self, script):
        r = subprocess.run([sys.executable, "-I", script], capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout

    def test_tree_equals_pre_install_after_pycache_written(self):
        for target in self.TARGETS:
            with self.subTest(target=target):
                self.setUp()
                before, script, pys = self.install(target)
                self.compile(pys)
                self.uninstall(script)
                self.assertEqual(snapshot(self.project), before)

    def test_foreign_file_in_pycache_keeps_the_whole_dir(self):
        for target in self.TARGETS:
            with self.subTest(target=target):
                self.setUp()
                _, script, pys = self.install(target)
                caches = sorted(self.compile(pys))
                foreign = os.path.join(caches[0], "user.txt")
                with open(foreign, "w", encoding="utf-8") as fh:
                    fh.write("mine")
                pycs = sorted(os.listdir(caches[0]))
                self.uninstall(script)
                self.assertTrue(os.path.isfile(foreign))
                self.assertEqual(sorted(os.listdir(caches[0])), pycs, "nothing in a foreign-holding dir is touched")

    def test_modified_py_keeps_its_pyc(self):
        for target in self.TARGETS:
            with self.subTest(target=target):
                self.setUp()
                _, script, pys = self.install(target)
                edited = next(p for p in pys if p.endswith("guard.py"))
                with open(edited, "a", encoding="utf-8") as fh:
                    fh.write("\n# user edit\n")
                self.compile(pys)
                out = self.uninstall(script)
                self.assertIn("kept (modified since install)", out)
                self.assertTrue(os.path.isfile(edited))
                pyc = [f for f in os.listdir(os.path.join(os.path.dirname(edited), "__pycache__"))
                       if f.startswith("guard.")]
                self.assertEqual(len(pyc), 1)


if __name__ == "__main__":
    unittest.main()
