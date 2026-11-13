"""Keychain storage: tokens move out of the credentials file into the OS keychain."""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import uuid
from contextlib import redirect_stderr
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                                "src", "skills", "mission-report", "scripts"))
os.environ["ACTIONBOARD_KEYCHAIN"] = "off"

import submit_mission  # noqa: E402
from actionboard_cli import keychain  # noqa: E402


class FakeKeychain:
    """In-memory backend with the same per-item size cap as Windows Credential Manager."""

    def __init__(self):
        self.items = {}
        self.fail_writes = False

    def set(self, name, value):
        if self.fail_writes:
            raise OSError("keychain locked")
        assert len(value) <= 2560
        self.items[name] = value

    def get(self, name):
        return self.items.get(name)

    def delete(self, name):
        return self.items.pop(name, None) is not None


class KeychainStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ab-keychain-")
        self.path = os.path.join(self.tmp, "credentials.json")
        self.fake = FakeKeychain()
        self.patches = [
            patch.dict(keychain._BACKENDS, {"fake": (self.fake.set, self.fake.get, self.fake.delete)}),
            patch.object(keychain, "backend_name", lambda: "fake"),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def file(self):
        with open(self.path, encoding="utf-8") as fh:
            return json.load(fh)

    def creds(self, size=100):
        return {
            "email": "dev@actionboard.ai",
            "edge_proxy_url": "https://edge.example",
            "access_token": "a" * size,
            "id_token": "i" * size,
            "refresh_token": "r" * size,
            "pod_tokens": {"pod-1": {"id_token": "p" * size}},
        }

    def test_secrets_leave_the_file_and_load_back(self):
        submit_mission.save_credentials(self.path, self.creds())
        on_disk = self.file()
        for key in keychain.SECRET_KEYS:
            self.assertNotIn(key, on_disk)
        self.assertEqual(on_disk["email"], "dev@actionboard.ai")
        self.assertEqual(on_disk["keychain_backend"], "fake")
        loaded = submit_mission.load_credentials(self.path)
        self.assertEqual(loaded["refresh_token"], "r" * 100)
        self.assertEqual(loaded["pod_tokens"], {"pod-1": {"id_token": "p" * 100}})

    def test_large_secrets_are_chunked_and_shrinking_removes_leftovers(self):
        submit_mission.save_credentials(self.path, self.creds(size=4000))
        self.assertGreater(len(self.fake.items), 3)
        self.assertEqual(submit_mission.load_credentials(self.path)["access_token"], "a" * 4000)
        loaded = submit_mission.load_credentials(self.path)
        loaded["pod_tokens"] = {}
        loaded["access_token"] = loaded["id_token"] = "x"
        loaded["refresh_token"] = "y"
        submit_mission.save_credentials(self.path, loaded)
        self.assertEqual(len(self.fake.items), 1)
        self.assertEqual(submit_mission.load_credentials(self.path)["refresh_token"], "y")

    def test_keychain_failure_keeps_tokens_in_the_file(self):
        submit_mission.save_credentials(self.path, self.creds())
        self.fake.fail_writes = True
        with redirect_stderr(io.StringIO()) as err:
            submit_mission.save_credentials(self.path, submit_mission.load_credentials(self.path))
        self.assertIn("could not save tokens", err.getvalue())
        on_disk = self.file()
        self.assertEqual(on_disk["refresh_token"], "r" * 100)
        self.assertNotIn("keychain_account", on_disk)
        self.assertEqual(self.fake.items, {})  # the stale keychain copy is removed

    def test_missing_keychain_item_means_logged_out(self):
        submit_mission.save_credentials(self.path, self.creds())
        self.fake.items.clear()
        with redirect_stderr(io.StringIO()) as err:
            loaded = submit_mission.load_credentials(self.path)
        self.assertIn("log in again", err.getvalue())
        self.assertNotIn("refresh_token", loaded)
        self.assertEqual(loaded["email"], "dev@actionboard.ai")

    def test_plaintext_file_is_migrated_on_first_read(self):
        submit_mission.save_secure_json(self.path, self.creds())
        loaded = submit_mission.load_credentials(self.path)
        self.assertEqual(loaded["refresh_token"], "r" * 100)
        self.assertNotIn("refresh_token", self.file())
        self.assertIn("keychain_account", self.file())

    def test_each_credentials_file_has_its_own_account(self):
        self.assertNotEqual(keychain.account_for(self.path), keychain.account_for(self.path + ".other"))

    def test_logout_removes_tokens_everywhere(self):
        submit_mission.save_credentials(self.path, self.creds())
        cwd = os.getcwd()
        os.chdir(self.tmp)
        try:
            with redirect_stderr(io.StringIO()):
                rc = submit_mission.main(["--credentials-file", self.path, "--config", os.path.join(self.tmp, "c.json"), "logout"])
        finally:
            os.chdir(cwd)
        self.assertEqual(rc, 0)
        self.assertEqual(self.fake.items, {})
        on_disk = self.file()
        self.assertNotIn("refresh_token", on_disk)
        self.assertNotIn("keychain_account", on_disk)
        self.assertEqual(on_disk["email"], "dev@actionboard.ai")

    def test_keychain_off_keeps_the_old_file_behaviour(self):
        with patch.object(keychain, "backend_name", lambda: None):
            submit_mission.save_credentials(self.path, self.creds())
        self.assertEqual(self.file()["refresh_token"], "r" * 100)
        self.assertEqual(self.fake.items, {})


@unittest.skipUnless(
    sys.platform == "win32" or os.environ.get("ACTIONBOARD_TEST_REAL_KEYCHAIN") == "1",
    "real keychain round trip runs on Windows CI, or locally with ACTIONBOARD_TEST_REAL_KEYCHAIN=1",
)
class RealKeychainTests(unittest.TestCase):
    def test_round_trip_through_the_os_keychain(self):
        with patch.dict(os.environ, {"ACTIONBOARD_KEYCHAIN": "auto"}):
            backend = keychain.backend_name()
        if backend is None:
            self.skipTest("no usable keychain on this machine")
        account = "selftest-" + uuid.uuid4().hex[:12]
        data = {"refresh_token": "r" * 5000, "pod_tokens": {"p": {"id_token": "t" * 3000}}}
        try:
            self.assertTrue(keychain.write_secret(account, data, backend))
            self.assertEqual(keychain.read_secret(account, backend), data)
            self.assertTrue(keychain.write_secret(account, {"refresh_token": "short"}, backend))
            self.assertEqual(keychain.read_secret(account, backend), {"refresh_token": "short"})
        finally:
            keychain.delete_secret(account, backend)
        self.assertIsNone(keychain.read_secret(account, backend))


if __name__ == "__main__":
    unittest.main()
