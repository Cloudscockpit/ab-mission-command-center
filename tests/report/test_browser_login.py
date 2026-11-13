"""Browser login: the CLI listens on localhost, the hosted login redirects back with a one-time key."""
import base64
import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
import urllib.request
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                                "src", "skills", "mission-report", "scripts"))
os.environ["ACTIONBOARD_KEYCHAIN"] = "off"

import submit_mission  # noqa: E402
from actionboard_cli.auth import _login_listeners  # noqa: E402
from test_submit_mission import FakeHTTPResponse as FakeResponse, MockActionBoardTransport  # noqa: E402


def decode_state(state):
    return base64.urlsafe_b64decode(state + "=" * (-len(state) % 4)).decode("utf-8")


def visit(url):
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code


class BrowserLoginTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ab-browser-login-")
        self.cred_file = os.path.join(self.tmp, "credentials.json")
        self.transport = MockActionBoardTransport()
        self.settings = submit_mission.resolve_settings(self.cred_file, os.path.join(self.tmp, "config.json"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def login(self, browser, **kwargs):
        kwargs.setdefault("timeout", 10)
        with patch("webbrowser.open", browser):
            return submit_mission.login_with_browser(self.settings, ports=(0,), opener=self.transport, **kwargs)

    def test_successful_sign_in_stores_tokens(self):
        seen = {}

        def browser(auth_url):
            parts = urllib.parse.urlparse(auth_url)
            query = dict(urllib.parse.parse_qsl(parts.query))
            seen.update(query, host=parts.netloc, path=parts.path)
            return_url = decode_state(query["state"])
            seen["return_url"] = return_url
            # A link from another login attempt is refused and does not end this one.
            seen["forged_status"] = visit(return_url.split("?")[0] + "?nonce=wrong&authorization-code=valid-key")
            seen["status"] = visit(return_url + "&authorization-code=valid-key")
            return True

        creds = self.login(browser)
        self.assertEqual(seen["host"], "absaas-dev.auth.ap-southeast-1.amazoncognito.com")
        self.assertEqual(seen["path"], "/oauth2/authorize")
        self.assertEqual(seen["client_id"], submit_mission.DEFAULT_COGNITO_CLIENT_ID)
        self.assertEqual(seen["redirect_uri"], submit_mission.DEFAULT_OAUTH_CALLBACK_URL)
        self.assertEqual(seen["response_type"], "code")
        self.assertNotIn("identity_provider", seen)
        self.assertTrue(seen["return_url"].startswith("http://localhost:"))
        self.assertIn("/actionboard-cli/callback?nonce=", seen["return_url"])
        self.assertEqual(seen["forged_status"], 400)
        self.assertEqual(seen["status"], 200)
        self.assertEqual(self.transport.exchanged_keys, ["valid-key"])
        self.assertEqual(creds["email"], "browser@actionboard.ai")
        with open(self.cred_file, encoding="utf-8") as fh:
            saved = json.load(fh)
        self.assertEqual(saved["refresh_token"], "refresh-from-browser")

    def test_provider_goes_straight_to_that_provider(self):
        seen = {}

        def browser(auth_url):
            query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(auth_url).query))
            seen.update(query)
            visit(decode_state(query["state"]) + "&authorization-code=valid-key")
            return True

        self.login(browser, provider="GitHub")
        self.assertEqual(seen["identity_provider"], "GitHub")

    def test_error_from_login_page_fails(self):
        def browser(auth_url):
            query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(auth_url).query))
            visit(decode_state(query["state"]) + "&error=access_denied")
            return True

        with self.assertRaises(SystemExit):
            self.login(browser)
        self.assertEqual(self.transport.exchanged_keys, [])

    def test_rejected_key_fails(self):
        def browser(auth_url):
            query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(auth_url).query))
            visit(decode_state(query["state"]) + "&authorization-code=expired-key")
            return True

        with self.assertRaises(SystemExit):
            self.login(browser)
        self.assertFalse(os.path.exists(self.cred_file))

    def test_timeout_fails(self):
        with self.assertRaises(SystemExit):
            self.login(lambda url: True, timeout=1)

    def test_busy_port_is_skipped(self):
        port, servers = _login_listeners((0,))
        try:
            again_port, again = _login_listeners((port,))
            self.assertIsNone(again_port)
            self.assertEqual(again, [])
        finally:
            for server in servers:
                server.server_close()


    def test_branded_page_returns_a_code_redeemed_with_the_pkce_verifier(self):
        self.settings["cli_login_url"] = "https://cli-login.example"
        seen, redeemed = {}, []
        real_transport = self.transport

        def opener(req, timeout=30):
            if req.full_url == "https://cli-login.example/api/cli/exchange":
                body = json.loads(req.data.decode("utf-8"))
                redeemed.append(body)
                challenge = base64.urlsafe_b64encode(hashlib.sha256(body["verifier"].encode()).digest()).decode().rstrip("=")
                ok = body["code"] == "sealed-code" and challenge == seen["challenge"]
                payload = {"success": ok, "message": "ok" if ok else "bad",
                           "data": {"tokens": {"accessToken": real_transport.main_access_token, "idToken": real_transport.main_id_token,
                                               "refreshToken": "refresh-from-page", "expiresIn": 3600},
                                    "user": {"profileId": "prof-agent-007", "userId": "u1", "email": "page@actionboard.ai"}} if ok else None}
                return FakeResponse(json.dumps(payload).encode())
            return real_transport(req, timeout=timeout)

        def browser(url):
            parts = urllib.parse.urlparse(url)
            query = dict(urllib.parse.parse_qsl(parts.query))
            seen.update(query, origin=parts.scheme + "://" + parts.netloc, path=parts.path)
            callback = "http://localhost:%s/actionboard-cli/callback?nonce=%s&cli-code=sealed-code" % (query["port"], query["nonce"])
            seen["status"] = visit(callback)
            return True

        with patch("webbrowser.open", browser):
            creds = submit_mission.login_with_browser(self.settings, ports=(0,), opener=opener, timeout=10)
        self.assertEqual(seen["origin"] + seen["path"], "https://cli-login.example/cli")
        self.assertEqual(len(seen["challenge"]), 43)
        self.assertEqual(seen["status"], 200)
        self.assertEqual(len(redeemed), 1)
        self.assertNotEqual(redeemed[0]["verifier"], seen["challenge"])
        self.assertEqual(creds["refresh_token"], "refresh-from-page")
        self.assertEqual(self.transport.exchanged_keys, [])

    def test_branded_page_social_buttons_still_use_the_cognito_key(self):
        self.settings["cli_login_url"] = "https://cli-login.example"

        def browser(url):
            query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
            visit("http://localhost:%s/actionboard-cli/callback?nonce=%s&authorization-code=valid-key" % (query["port"], query["nonce"]))
            return True

        creds = self.login(browser)
        self.assertEqual(self.transport.exchanged_keys, ["valid-key"])
        self.assertEqual(creds["email"], "browser@actionboard.ai")

    def test_provider_skips_the_branded_page(self):
        self.settings["cli_login_url"] = "https://cli-login.example"
        seen = {}

        def browser(url):
            parts = urllib.parse.urlparse(url)
            query = dict(urllib.parse.parse_qsl(parts.query))
            seen.update(host=parts.netloc, provider=query.get("identity_provider"))
            visit(decode_state(query["state"]) + "&authorization-code=valid-key")
            return True

        self.login(browser, provider="Google")
        self.assertEqual(seen["host"], "absaas-dev.auth.ap-southeast-1.amazoncognito.com")
        self.assertEqual(seen["provider"], "Google")

    def test_rejected_page_code_fails(self):
        self.settings["cli_login_url"] = "https://cli-login.example"

        def opener(req, timeout=30):
            if req.full_url.endswith("/api/cli/exchange"):
                return FakeResponse(json.dumps({"success": False, "message": "Sign-in code is invalid or expired."}).encode())
            return self.transport(req, timeout=timeout)

        def browser(url):
            query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
            visit("http://localhost:%s/actionboard-cli/callback?nonce=%s&cli-code=stale" % (query["port"], query["nonce"]))
            return True

        with patch("webbrowser.open", browser):
            with self.assertRaises(SystemExit):
                submit_mission.login_with_browser(self.settings, ports=(0,), opener=opener, timeout=10)
        self.assertFalse(os.path.exists(self.cred_file))


if __name__ == "__main__":
    unittest.main()
