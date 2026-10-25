"""uvx twin of the npx installer (packages/installer-py/actionboard_install): offline unit tests.

    python -m unittest discover -s tests/installer -v
"""

import contextlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
import urllib.error
from email.message import Message
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "packages", "installer-py"))

from actionboard_install import __main__ as ab  # noqa: E402

FAKE_INSTALL = (
    "import json, os, sys\n"
    "with open(os.path.join(os.getcwd(), 'marker.json'), 'w') as f:\n"
    "    json.dump({'argv': sys.argv[1:], 'file': os.path.abspath(__file__)}, f)\n"
    "sys.exit(int(os.environ.get('FAKE_EXIT', '0')))\n"
)


def add(tar, name, data=b"", kind=tarfile.REGTYPE, link=None):
    info = tarfile.TarInfo(name)
    info.type = kind
    if link:
        info.linkname = link
    if kind == tarfile.REGTYPE:
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    else:
        tar.addfile(info)


def make_tar(path, members):
    with tarfile.open(path, "w:gz") as tar:
        for m in members:
            add(tar, *m[:1], **m[1])
    return path


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.dest = os.path.join(self.tmp, "a", "dest")
        os.makedirs(self.dest)
        self.outside = os.path.join(self.tmp, "a")  # parent of dest


def without_data_filter():
    """Simulate an older Python (3.9-3.11 before the filter backport) so the manual checks run."""
    class Old:
        def __getattr__(self, name):
            if name == "data_filter":
                raise AttributeError(name)
            return getattr(tarfile, name)

        def open(self, *args, **kwargs):
            tar = tarfile.open(*args, **kwargs)
            real = tar.extractall
            # old Pythons extract with no filter at all
            tar.extractall = lambda path, **kw: real(path, filter="fully_trusted") \
                if hasattr(tarfile, "fully_trusted_filter") else real(path)
            return tar
    return mock.patch.object(ab, "tarfile", Old())


class SafeExtract(Base):
    def extract(self, members, legacy=False):
        arc = make_tar(os.path.join(self.tmp, "x.tar.gz"), members)
        ctx = without_data_filter() if legacy else contextlib.nullcontext()
        with ctx:
            ab.safe_extract(arc, self.dest)

    def test_normal_bundle(self):
        for legacy in (False, True):
            self.extract([("top/scripts/install.py", {"data": b"print(1)"})], legacy)
            self.assertTrue(os.path.isfile(os.path.join(self.dest, "top", "scripts", "install.py")))
            self.assertEqual(os.path.basename(ab.find_top(self.dest)), "top")

    def test_rejects_traversal_and_absolute_members(self):
        for legacy in (False, True):
            with self.assertRaises((ab.InstallerError, tarfile.TarError)):
                self.extract([("top/ok", {"data": b"x"}), ("../evil.txt", {"data": b"pwned"})], legacy)
            self.assertFalse(os.path.exists(os.path.join(self.outside, "evil.txt")))
            absolute = os.path.join(self.tmp, "evil-abs.txt").replace("\\", "/")
            try:
                self.extract([(absolute, {"data": b"pwned"})], legacy)
            except (ab.InstallerError, tarfile.TarError):
                pass
            self.assertFalse(os.path.exists(os.path.join(self.tmp, "evil-abs.txt")))

    def test_rejects_symlink_escape(self):
        victim = os.path.join(self.tmp, "victim")
        os.makedirs(victim)
        for legacy in (False, True):
            with self.assertRaises((ab.InstallerError, tarfile.TarError, OSError)):
                self.extract([("top/link", {"kind": tarfile.SYMTYPE, "link": victim.replace("\\", "/")}),
                              ("top/link/pwned.txt", {"data": b"pwned"})], legacy)
            self.assertEqual(os.listdir(victim), [])
            with self.assertRaises((ab.InstallerError, tarfile.TarError, OSError)):
                self.extract([("top/rel", {"kind": tarfile.SYMTYPE, "link": "../../../victim"}),
                              ("top/rel/pwned.txt", {"data": b"pwned"})], legacy)
            self.assertEqual(os.listdir(victim), [])

    def test_legacy_fallback_symlink_chain_cannot_escape(self):
        """a -> . ; a/b -> ../.. ; a/b/pwned.txt. Each name looks inside dest when checked
        lexically, but once 'a' exists a/b points above dest. Python without tarfile.data_filter
        relies on these checks alone."""
        arc = make_tar(os.path.join(self.tmp, "chain.tar.gz"), [
            ("top/a", {"kind": tarfile.SYMTYPE, "link": "."}),
            ("top/a/b", {"kind": tarfile.SYMTYPE, "link": "../.."}),
            ("top/a/b/pwned.txt", {"data": b"pwned"}),
        ])
        try:
            with without_data_filter():
                ab.safe_extract(arc, self.dest)
        except (ab.InstallerError, tarfile.TarError, OSError):
            pass
        self.assertFalse(os.path.exists(os.path.join(self.outside, "pwned.txt")),
                         "legacy extractor let a symlink chain write outside the destination")

    def test_find_top(self):
        os.makedirs(os.path.join(self.dest, "one"))
        self.assertEqual(ab.find_top(self.dest), os.path.join(self.dest, "one"))
        os.makedirs(os.path.join(self.dest, "two"))
        with self.assertRaises(ab.InstallerError):
            ab.find_top(self.dest)


class Ephemeral(Base):
    def test_uv_cache_and_uvx_environments(self):
        cache = os.path.join(self.tmp, "uvcache")
        exe = os.path.join(cache, "archive-v0", "abc", "bin", "python")
        os.makedirs(os.path.dirname(exe))
        with mock.patch.dict(os.environ, {"UV_CACHE_DIR": cache}):
            self.assertTrue(ab._is_ephemeral(exe, os.path.join(cache, "archive-v0", "abc")))
        # uv layout recognised even when the cache dir is not announced
        with mock.patch.dict(os.environ, {"UV_CACHE_DIR": os.path.join(self.tmp, "elsewhere")}):
            self.assertTrue(ab._is_ephemeral(exe, os.path.dirname(exe)))
            envs = os.path.join(self.tmp, "x", "environments-v2", "tool-1", "bin", "python")
            self.assertTrue(ab._is_ephemeral(envs, os.path.dirname(envs)))

    def test_persistent_python_is_not_ephemeral(self):
        exe = os.path.join(self.tmp, "Python314", "python.exe")
        os.makedirs(os.path.dirname(exe))
        with mock.patch.dict(os.environ, {"UV_CACHE_DIR": os.path.join(self.tmp, "uvcache")}):
            self.assertFalse(ab._is_ephemeral(exe, os.path.dirname(exe)))

    def test_current_venv_is_ephemeral(self):
        venv = os.path.join(self.tmp, "venv")
        exe = os.path.join(venv, "bin", "python")
        os.makedirs(os.path.dirname(exe))
        with mock.patch.object(sys, "prefix", venv), mock.patch.object(sys, "base_prefix", self.tmp):
            self.assertTrue(ab._is_ephemeral(exe, venv))


class ResolvePython(unittest.TestCase):
    @staticmethod
    def runner(table):
        def run(cmd, **kw):
            self_cmd = cmd[0]
            res = table.get(self_cmd)
            if isinstance(res, Exception):
                raise res
            if res is None:
                return subprocess.CompletedProcess(cmd, 1, "", "")
            return subprocess.CompletedProcess(cmd, res[0], res[1], "")
        return run

    def test_isolated_probe(self):
        seen = []

        def run(cmd, **kw):
            seen.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "True\n/usr/bin/python3\n/usr\n", "")
        with mock.patch.object(ab, "_is_ephemeral", return_value=False):
            ab.resolve_python({}, which=lambda n: "/bin/" + n, run=run)
        self.assertIn("-I", seen[0])

    def test_skips_stub_old_and_ephemeral(self):
        found = {"py": "/bin/py", "python3": "/bin/python3", "python": "/bin/python"}
        table = {
            "/bin/py": (0, ""),                                    # Store stub: quiet success, no output
            "/bin/python3": (0, "False\n/old/python\n/old\n"),     # < 3.9
            "/bin/python": (0, "True\n/real/python\n/real\n"),
        }
        with mock.patch.object(ab, "_is_ephemeral", return_value=False):
            exe, warn = ab.resolve_python({}, which=found.get, run=self.runner(table))
        self.assertEqual(exe, "/real/python")
        self.assertIsNone(warn)
        table["/bin/python"] = (0, "True\n/uvx/env/bin/python\n/uvx/env\n")
        with mock.patch.object(ab, "_is_ephemeral", side_effect=lambda e, p: "uvx" in e), \
                mock.patch.object(sys, "_base_executable", None, create=True):
            with self.assertRaises(ab.InstallerError):
                ab.resolve_python({}, which=found.get, run=self.runner(table))

    def test_falls_back_to_base_executable_with_warning(self):
        base = sys.executable
        with mock.patch.object(sys, "_base_executable", base, create=True):
            exe, warn = ab.resolve_python({}, which=lambda n: None, run=self.runner({}))
        self.assertEqual(exe, base)
        self.assertIn("no persistent Python", warn)

    def test_actionboard_python_must_work(self):
        good = self.runner({"/x/python": (0, "True\n/x/python\n/x\n")})
        self.assertEqual(ab.resolve_python({"ACTIONBOARD_PYTHON": "/x/python"}, which=lambda n: None, run=good)[0],
                         "/x/python")
        with self.assertRaises(ab.InstallerError):
            ab.resolve_python({"ACTIONBOARD_PYTHON": "/nope"}, which=lambda n: None, run=self.runner({"/nope": OSError("x")}))

    def test_probe_survives_timeouts(self):
        self.assertIsNone(ab._probe(["/x"], self.runner({"/x": subprocess.TimeoutExpired("x", 1)})))


class Args(unittest.TestCase):
    def parse(self, *argv):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            return ab.parse_args(list(argv), cwd=os.path.abspath(os.sep + "work")), err

    def test_targets_and_absolute_project(self):
        for t in ab.TARGETS:
            a, _ = self.parse("--target", t, "--project", "rel/p")
            self.assertEqual(ab.build_install_args(a)[:4], ["--target", t, "--project", a.project_abs])
            self.assertTrue(os.path.isabs(a.project_abs))

    def test_rejections_exit_2(self):
        for argv in (["--target", "claude"], ["--target", "all"], ["--target", "vim"], [],
                     ["--target", "codex", "--global", "--project", "x"], ["--target", "codex", "--cleanup"]):
            with self.assertRaises(SystemExit) as cm:
                self.parse(*argv)
            self.assertEqual(cm.exception.code, 2, argv)

    def test_global_has_no_project_and_flags_pass_through(self):
        a, _ = self.parse("--target", "opencode", "--global", "--uninstall", "--dry-run", "--yes", "--force",
                          "--with", "graphify", "--without", "terse")
        self.assertEqual(ab.build_install_args(a), ["--target", "opencode", "--global", "--uninstall", "--dry-run",
                                                    "--yes", "--force", "--with", "graphify", "--without", "terse"])


class Download(unittest.TestCase):
    @staticmethod
    def http_error(url, code, location=None):
        hdrs = Message()
        if location:
            hdrs["Location"] = location
        return urllib.error.HTTPError(url, code, "x", hdrs, None)

    def test_refuses_non_https_before_any_io(self):
        opener = mock.Mock()
        for url in ("http://example.invalid/x", "file:///etc/passwd", "ftp://x/y"):
            with self.assertRaises(ab.InstallerError):
                ab.download(url, os.devnull, opener=opener)
        opener.open.assert_not_called()

    def test_redirect_to_http_is_refused(self):
        opener = mock.Mock()
        opener.open.side_effect = self.http_error("https://a.example/x", 302, "http://evil.example/x")
        with self.assertRaisesRegex(ab.InstallerError, "non-https"):
            ab.download("https://a.example/x", os.devnull, opener=opener)

    def test_redirect_loop_is_bounded(self):
        opener = mock.Mock()
        opener.open.side_effect = self.http_error("https://a.example/x", 302, "/x")
        with self.assertRaisesRegex(ab.InstallerError, "too many redirects"):
            ab.download("https://a.example/x", os.devnull, opener=opener)
        self.assertLessEqual(opener.open.call_count, ab.MAX_REDIRECTS + 1)

    def test_404_names_the_unpublished_tag(self):
        opener = mock.Mock()
        opener.open.side_effect = self.http_error("https://a.example/x", 404)
        with self.assertRaisesRegex(ab.InstallerError, "not found"):
            ab.download("https://a.example/x", os.devnull, opener=opener)

    def test_http_never_builds_an_opener(self):
        with mock.patch.object(ab.urllib.request, "build_opener", wraps=ab.urllib.request.build_opener) as bo:
            with self.assertRaises(ab.InstallerError):
                ab.download("http://example.invalid/x", os.devnull)
            bo.assert_not_called()


class RunEndToEnd(Base):
    def bundle(self, members):
        return make_tar(os.path.join(self.tmp, "bundle.tar.gz"), members)

    def run_ab(self, bundle, argv, **env):
        scratch = os.path.join(self.tmp, "scratch")
        os.makedirs(scratch, exist_ok=True)
        full = dict(ACTIONBOARD_BUNDLE=bundle, ACTIONBOARD_PYTHON=sys.executable)
        full.update(env)
        err = io.StringIO()
        with mock.patch.dict(os.environ, full), mock.patch.object(tempfile, "tempdir", scratch), \
                contextlib.redirect_stderr(err):
            code = ab.run(argv)
        return code, err.getvalue(), scratch

    def test_argv_exit_code_and_temp_cleanup(self):
        project = os.path.join(self.tmp, "proj")
        bundle = self.bundle([("ab-1.1.0/scripts/install.py", {"data": FAKE_INSTALL.encode()})])
        code, _, scratch = self.run_ab(bundle, ["--target", "codex", "--project", project, "--yes"])
        self.assertEqual(code, 0)
        with open(os.path.join(project, "marker.json"), encoding="utf-8") as fh:
            m = json.load(fh)
        self.assertEqual(m["argv"], ["--target", "codex", "--project", os.path.abspath(project), "--yes"])
        self.assertIn("actionboard-install-", m["file"])
        self.assertEqual(os.listdir(scratch), [])
        code, _, scratch = self.run_ab(bundle, ["--target", "codex", "--project", project], FAKE_EXIT="3")
        self.assertEqual(code, 3)
        self.assertEqual(os.listdir(scratch), [])

    def test_missing_bundle_and_hostile_bundle(self):
        project = os.path.join(self.tmp, "proj")
        code, err, scratch = self.run_ab(os.path.join(self.tmp, "nope.tgz"), ["--target", "codex", "--project", project])
        self.assertEqual(code, 1)
        self.assertIn("bundle not found", err)
        self.assertEqual(os.listdir(scratch), [])
        bundle = self.bundle([("ab/scripts/install.py", {"data": FAKE_INSTALL.encode()}),
                              ("../../../../evil.txt", {"data": b"pwned"})])
        code, err, scratch = self.run_ab(bundle, ["--target", "codex", "--project", project])
        self.assertEqual(code, 1)
        self.assertFalse(os.path.exists(os.path.join(project, "marker.json")))
        self.assertEqual(os.listdir(scratch), [])


if __name__ == "__main__":
    unittest.main()
