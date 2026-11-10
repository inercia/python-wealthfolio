"""Offline checks that the skill launcher delegates without changing CLI policy."""

from pathlib import Path
import os
import runpy
import sys
import unittest
from unittest import mock


LAUNCHER = (
    Path(__file__).resolve().parents[1]
    / "skills" / "wealthfolio-cli" / "scripts" / "wealthfolio_cli.py"
)


class SkillLauncherTests(unittest.TestCase):
    def test_dependency_tracks_main(self):
        self.assertIn(
            '"python-wealthfolio @ git+https://github.com/inercia/python-wealthfolio.git@main",',
            LAUNCHER.read_text(encoding="utf-8"),
        )

    def test_dispatch_preserves_arguments_and_exit_status_without_dotenv(self):
        env = {"WEALTHFOLIO_REST_URL": "https://example.invalid", "WEALTHFOLIO_PASSWORD": "test"}
        handler = mock.Mock(side_effect=SystemExit(7))
        parser = mock.Mock()
        args = parser.parse_args.return_value
        args.func = handler
        args.yes = False
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch("wealthfolio.config.load_dotenv") as dotenv:
                with mock.patch("wealthfolio.cli.build_parser", return_value=parser):
                    with self.assertRaises(SystemExit) as result:
                        runpy.run_path(str(LAUNCHER), run_name="__main__")
        self.assertEqual(result.exception.code, 7)
        parser.parse_args.assert_called_once_with()
        handler.assert_called_once_with(args)
        self.assertFalse(args.yes)
        dotenv.assert_not_called()

    def test_missing_or_blank_environment_blocks_dispatch(self):
        for env in ({}, {"WEALTHFOLIO_REST_URL": "https://example.invalid"},
                    {"WEALTHFOLIO_PASSWORD": "test"},
                    {"WEALTHFOLIO_REST_URL": " ", "WEALTHFOLIO_PASSWORD": "test"},
                    {"WEALTHFOLIO_REST_URL": "https://example.invalid", "WEALTHFOLIO_PASSWORD": " "}):
            with self.subTest(env_keys=tuple(env)):
                with mock.patch.dict(os.environ, env, clear=True):
                    with mock.patch.object(sys, "argv", [str(LAUNCHER), "accounts"]):
                        with mock.patch("wealthfolio.config.load_dotenv") as dotenv:
                            with mock.patch("sys.stderr"):
                                with self.assertRaises(SystemExit) as result:
                                    runpy.run_path(str(LAUNCHER), run_name="__main__")
                self.assertEqual(result.exception.code, 2)
                dotenv.assert_not_called()

    def test_help_needs_no_environment(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch.object(sys, "argv", [str(LAUNCHER), "--help"]):
                with mock.patch("sys.stdout"):
                    with self.assertRaises(SystemExit) as result:
                        runpy.run_path(str(LAUNCHER), run_name="__main__")
        self.assertEqual(result.exception.code, 0)

    def test_import_does_not_run_cli(self):
        with mock.patch("wealthfolio.cli.build_parser") as main:
            runpy.run_path(str(LAUNCHER), run_name="skill_launcher")
            main.assert_not_called()
