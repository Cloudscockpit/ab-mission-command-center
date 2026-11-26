"""ab-signup: regional sign-up URL, page opener, `signup` parser and cmd_signup flows. No real browser, network or keychain."""
import argparse
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import webbrowser
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                                "src", "skills", "mission-report", "scripts"))
os.environ["ACTIONBOARD_KEYCHAIN"] = "off"

import submit_mission  # noqa: E402
from actionboard_cli import commands  # noqa: E402
from actionboard_cli.auth import SignupRegionPending, open_signup_page, signup_url  # noqa: E402

BD_URL = "https://actionboard.com.bd/auth/signup"
US_URL = "https://actionboard.ai/auth/signup"


class SignupUrlTests(unittest.TestCase):
    def test_bd_variants_give_exact_url(self):
        for value in ("bd", "BD", " bd "):
            self.assertEqual(signup_url(value), BD_URL)

    def test_us_gives_exact_url(self):
        self.assertEqual(signup_url("us"), US_URL)

    def test_invalid_regions_raise_and_name_valid_codes(self):
        for value in ("eu", "", None, "https://evil.example", 5):
            with self.assertRaises(ValueError) as ctx:
                signup_url(value)
            self.assertIn("bd", str(ctx.exception))
            self.assertIn("us", str(ctx.exception))


class OpenSignupPageTests(unittest.TestCase):
    def test_bd_opens_exact_url_once(self):
        browser = MagicMock(return_value=True)
        result = open_signup_page("bd", browser_open=browser)
        browser.assert_called_once_with(BD_URL)
        self.assertEqual(result["signup_url"], BD_URL)
        self.assertEqual(result["region"], "bd")
        self.assertTrue(result["opened"])

    def test_us_is_pending_and_does_not_open(self):
        browser = MagicMock(return_value=True)
        with self.assertRaises(SignupRegionPending) as ctx:
            open_signup_page("us", browser_open=browser)
        browser.assert_not_called()
        self.assertEqual(ctx.exception.signup_url, US_URL)
        self.assertEqual(ctx.exception.region, "us")

    def test_opened_false_when_browser_returns_false_or_none(self):
        for ret in (False, None):
            result = open_signup_page("bd", browser_open=MagicMock(return_value=ret))
            self.assertFalse(result["opened"])

    def test_opened_false_when_browser_raises_webbrowser_error(self):
        result = open_signup_page("bd", browser_open=MagicMock(side_effect=webbrowser.Error("no browser")))
        self.assertFalse(result["opened"])

    def test_invalid_region_raises_before_opening(self):
        browser = MagicMock()
        with self.assertRaises(ValueError):
            open_signup_page("eu", browser_open=browser)
        browser.assert_not_called()


class SignupParserTests(unittest.TestCase):
    def signup_parser(self):
        parser = commands.build_parser()
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                return action.choices["signup"]
        self.fail("no subparsers")

    def test_no_secret_or_target_options(self):
        banned = ("password", "code", "email", "url", "host")
        for action in self.signup_parser()._actions:
            for name in [action.dest] + list(action.option_strings):
                for word in banned:
                    self.assertNotIn(word, name.lower(), "signup option %r exposes %s" % (name, word))

    def test_rejects_password_flag(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            commands.build_parser().parse_args(["signup", "--password", "x"])


class CmdSignupBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ab-signup-")
        self.cred_file = os.path.join(self.tmp, "credentials.json")
        self.config = os.path.join(self.tmp, "config.json")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        patcher = patch.object(commands, "_browser_login", return_value={"email": "a@example.com"})
        self.login = patcher.start()
        self.addCleanup(patcher.stop)

    def run_signup(self, argv, isatty=False, inputs=None, browser_ret=True, pods=None, creds=None, token_valid=True):
        argv = ["signup", "--credentials-file", self.cred_file, "--config", self.config] + list(argv)
        args = commands.build_parser().parse_args(argv)
        browser = MagicMock(return_value=browser_ret)
        out, err = io.StringIO(), io.StringIO()
        input_mock = MagicMock(side_effect=inputs if inputs is not None else AssertionError("unexpected input()"))
        settings = {"creds": creds or {}, "cred_file": self.cred_file}
        pods_mock = MagicMock(return_value=pods if pods is not None else [{"id": "p"}])
        code = None
        with patch("sys.stdin.isatty", return_value=isatty), patch("builtins.input", input_mock), \
                patch("actionboard_cli.auth.resolve_settings", return_value=settings), \
                patch("actionboard_cli.auth.fetch_my_pods", pods_mock), \
                patch("actionboard_cli.auth.ensure_main_token", return_value="tok"), \
                patch("actionboard_cli.auth.token_is_valid", return_value=token_valid), \
                redirect_stdout(out), redirect_stderr(err):
            try:
                code = commands.cmd_signup(args, opener=object(), browser_open=browser)
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue(), browser, input_mock, pods_mock


class CmdSignupNoInputTests(CmdSignupBase):
    def test_bd_json_success_next_step_login(self):
        code, out, _, browser, _, _ = self.run_signup(["--region", "bd", "--no-input", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertTrue(data["success"])
        self.assertEqual(data["next_step"], "login")
        self.assertEqual(data["signup_url"], BD_URL)
        browser.assert_called_once_with(BD_URL)
        self.login.assert_not_called()

    def test_us_json_is_region_pending(self):
        code, out, _, browser, _, _ = self.run_signup(["--region", "us", "--no-input", "--json"])
        self.assertNotIn(code, (0, None))
        data = json.loads(out)
        self.assertEqual(data["status"], "region_pending")
        self.assertFalse(data["success"])
        browser.assert_not_called()
        self.login.assert_not_called()

    def test_us_plain_text_fails_without_browser(self):
        code, _, err, browser, _, _ = self.run_signup(["--region", "us", "--no-input"])
        self.assertNotIn(code, (0, None))
        self.assertIn(US_URL, err)
        browser.assert_not_called()

    def test_missing_region_with_no_input_names_choices(self):
        code, _, err, browser, _, _ = self.run_signup(["--no-input", "--json"], isatty=True)
        self.assertNotIn(code, (0, None))
        self.assertIn("bd", err)
        self.assertIn("us", err)
        browser.assert_not_called()

    def test_missing_region_without_tty_fails(self):
        code, _, err, browser, _, _ = self.run_signup([], isatty=False)
        self.assertNotIn(code, (0, None))
        self.assertIn("--region", err)
        browser.assert_not_called()

    def test_invalid_region_fails(self):
        for value in ("eu", "https://evil.example"):
            code, _, err, browser, _, _ = self.run_signup(["--region", value, "--no-input"])
            self.assertNotIn(code, (0, None))
            self.assertIn("bd", err)
            browser.assert_not_called()

    def test_region_is_normalised(self):
        code, _, _, browser, _, _ = self.run_signup(["--region", " BD ", "--no-input", "--json"])
        self.assertEqual(code, 0)
        browser.assert_called_once_with(BD_URL)

    def test_no_input_plain_text_prints_login_hint_and_never_logs_in(self):
        code, out, _, _, _, _ = self.run_signup(["--region", "bd", "--no-input"], isatty=True)
        self.assertEqual(code, 0)
        self.assertIn("submit_mission.py login", out)
        self.assertIn("never in a chat", out)
        self.login.assert_not_called()

    def test_browser_not_opened_prints_link(self):
        _, out, _, _, _, _ = self.run_signup(["--region", "bd", "--no-input"], browser_ret=False)
        self.assertIn(BD_URL, out)


class CmdSignupInteractiveTests(CmdSignupBase):
    def test_region_prompt_then_enter_logs_in_once_with_no_provider(self):
        code, out, _, browser, inp, pods = self.run_signup([], isatty=True, inputs=["1", ""])
        self.assertEqual(code, 0)
        browser.assert_called_once_with(BD_URL)
        self.login.assert_called_once()
        self.assertIsNone(self.login.call_args[0][1])
        self.assertEqual(inp.call_count, 2)
        pods.assert_called_once()
        self.assertNotIn("no Pod", out)

    def test_region_flag_skips_region_prompt(self):
        code, _, _, _, inp, _ = self.run_signup(["--region", "bd"], isatty=True, inputs=[""])
        self.assertEqual(code, 0)
        self.assertEqual(inp.call_count, 1)
        self.login.assert_called_once()

    def test_us_choice_in_prompt_is_pending(self):
        code, _, _, browser, _, _ = self.run_signup([], isatty=True, inputs=["2"])
        self.assertNotIn(code, (0, None))
        browser.assert_not_called()
        self.login.assert_not_called()

    def test_empty_pods_prints_no_pod_message(self):
        code, out, _, _, _, _ = self.run_signup(["--region", "bd"], isatty=True, inputs=[""], pods=[])
        self.assertEqual(code, 0)
        self.assertIn("no Pod", out)

    def test_existing_session_declined_by_n_or_empty(self):
        creds = {"access_token": "a", "email": "old@example.com"}
        for answer in ("n", ""):
            self.login.reset_mock()
            code, out, _, _, _, _ = self.run_signup(["--region", "bd"], isatty=True, inputs=["", answer], creds=creds)
            self.assertEqual(code, 0)
            self.login.assert_not_called()
            self.assertIn("not changed", out)

    def test_existing_session_confirmed_by_y(self):
        creds = {"refresh_token": "r", "email": "old@example.com"}
        code, _, _, _, _, _ = self.run_signup(["--region", "bd"], isatty=True, inputs=["", "y"], creds=creds)
        self.assertEqual(code, 0)
        self.login.assert_called_once()

    def test_eof_at_verified_prompt_exits_cleanly(self):
        code, out, err, _, _, _ = self.run_signup(["--region", "bd"], isatty=True, inputs=[EOFError()])
        self.assertEqual(code, 1)
        self.assertNotIn("Traceback", out + err)
        self.login.assert_not_called()

    def test_keyboard_interrupt_at_verified_prompt_exits_cleanly(self):
        code, out, err, _, _, _ = self.run_signup(["--region", "bd"], isatty=True, inputs=[KeyboardInterrupt()])
        self.assertEqual(code, 1)
        self.assertNotIn("Traceback", out + err)
        self.login.assert_not_called()

    def test_eof_at_region_prompt_exits_cleanly(self):
        code, _, err, browser, _, _ = self.run_signup([], isatty=True, inputs=[EOFError()])
        self.assertNotIn(code, (0, None))
        self.assertNotIn("Traceback", err)
        browser.assert_not_called()

    def test_keyboard_interrupt_at_region_prompt_is_handled(self):
        # prompt_choice only catches EOFError, so Ctrl+C here escapes cmd_signup as KeyboardInterrupt.
        try:
            code, _, _, browser, _, _ = self.run_signup([], isatty=True, inputs=[KeyboardInterrupt()])
        except KeyboardInterrupt:
            self.fail("KeyboardInterrupt escaped cmd_signup at the region prompt (would print a traceback)")
        self.assertNotIn(code, (0, None))
        browser.assert_not_called()

    def test_eof_at_replace_session_prompt_is_handled(self):
        creds = {"access_token": "a", "email": "old@example.com"}
        try:
            self.run_signup(["--region", "bd"], isatty=True, inputs=["", EOFError()], creds=creds)
        except EOFError:
            self.fail("EOFError escaped cmd_signup at the replace-session confirmation")
        self.login.assert_not_called()

    def test_keyboard_interrupt_at_replace_session_prompt_is_handled(self):
        creds = {"access_token": "a", "email": "old@example.com"}
        try:
            self.run_signup(["--region", "bd"], isatty=True, inputs=["", KeyboardInterrupt()], creds=creds)
        except KeyboardInterrupt:
            self.fail("KeyboardInterrupt escaped cmd_signup at the replace-session confirmation")
        self.login.assert_not_called()


class MainDispatchTests(unittest.TestCase):
    def test_main_signup_us_never_opens_browser(self):
        with patch("webbrowser.open") as wb, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), \
                self.assertRaises(SystemExit) as ctx:
            submit_mission.main(["signup", "--region", "us", "--no-input", "--json"])
        wb.assert_not_called()
        self.assertEqual(ctx.exception.code, 2)

    def test_main_signup_bd_no_input_opens_exact_url_only(self):
        with patch("webbrowser.open", return_value=True) as wb, patch.object(commands, "_browser_login") as login, \
                redirect_stdout(io.StringIO()):
            self.assertEqual(submit_mission.main(["signup", "--region", "bd", "--no-input", "--json"]), 0)
        wb.assert_called_once_with(BD_URL)
        login.assert_not_called()


class LoginRefactorTests(unittest.TestCase):
    """cmd_login's browser branch must still delegate to login_with_browser with the same arguments."""

    def test_cmd_login_browser_path_passes_arguments_through(self):
        tmp = tempfile.mkdtemp(prefix="ab-signup-login-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        args = commands.build_parser().parse_args([
            "login", "--credentials-file", os.path.join(tmp, "c.json"), "--config", os.path.join(tmp, "cfg.json"),
            "--no-browser", "--timeout", "7", "--provider", "Google"])
        opener = object()
        with patch("actionboard_cli.auth.login_with_browser", return_value={"email": "a@example.com"}) as lwb, \
                redirect_stdout(io.StringIO()):
            self.assertEqual(commands.cmd_login(args, opener=opener), 0)
        _, kwargs = lwb.call_args
        self.assertEqual(kwargs["provider"], "Google")
        self.assertFalse(kwargs["open_browser"])
        self.assertEqual(kwargs["timeout"], 7)
        self.assertIs(kwargs["opener"], opener)


if __name__ == "__main__":
    unittest.main()
