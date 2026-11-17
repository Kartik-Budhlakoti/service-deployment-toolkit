from contextlib import redirect_stderr, redirect_stdout
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from toolkit.cli import main
from toolkit.config import ConfigurationError, Settings, validate_image, validate_release


class CommandTests(unittest.TestCase):
    def setUp(self):
        state = patch("toolkit.cli.read_state", return_value={
            "version": 1, "latest": None, "last_success": None,
        })
        state.start()
        self.addCleanup(state.stop)

    def invoke(self, arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                code = main(arguments)
            except SystemExit as error:
                code = error.code
        return code, stdout.getvalue(), stderr.getvalue()

    def arguments(self, command="validate"):
        return [command, "--image", "sdt-demo-api:phase1", "--release", "demo-v1"]

    def test_valid_input_is_not_reported_as_a_deployment(self):
        code, output, error = self.invoke(self.arguments())
        self.assertEqual(code, 0)
        self.assertIn("have NOT been checked", output)
        self.assertEqual(error, "")

    def test_valid_deploy_is_explicitly_unavailable(self):
        code, output, error = self.invoke(self.arguments("deploy"))
        self.assertEqual(code, 3)
        self.assertEqual(output, "")
        self.assertIn("nothing was changed", error)

    def test_status_does_not_claim_observed_health(self):
        with patch("toolkit.cli.inspect_status", return_value=[]):
            code, output, error = self.invoke(["status"])
        self.assertEqual(code, 0)
        self.assertIn("no sdt-demo containers", output)
        self.assertIn("OBSERVATION ONLY", output)
        self.assertEqual(error, "")

    def test_help_succeeds(self):
        for command in ([], ["validate"], ["deploy"], ["status"], ["preflight"]):
            with self.subTest(command=command):
                self.assertEqual(self.invoke(command + ["--help"])[0], 0)

    def test_missing_and_unknown_arguments_fail(self):
        cases = [[], ["rollback"], ["deploy"], ["validate", "--image", "a:v1"],
                 self.arguments() + ["--unknown"], ["status", "--image", "a:v1"]]
        for arguments in cases:
            with self.subTest(arguments=arguments):
                self.assertEqual(self.invoke(arguments)[0], 2)

    def test_abbreviated_flags_fail(self):
        self.assertEqual(self.invoke(["validate", "--ima", "a:v1", "--release", "v1"])[0], 2)

    def test_invalid_timeout_cli_inputs_fail(self):
        for value in ("0", "-1", "601", "nan", "inf", "1.5"):
            with self.subTest(value=value):
                self.assertEqual(self.invoke(self.arguments() + ["--verification-timeout", value])[0], 2)

    def test_invalid_image_and_release_fail_for_both_commands(self):
        for command in ("validate", "deploy"):
            for image, release in (("untagged", "v1"), ("a:v1", "bad release")):
                with self.subTest(command=command, image=image, release=release):
                    self.assertEqual(self.invoke([command, "--image", image, "--release", release])[0], 2)

    def test_commands_do_not_launch_subprocesses(self):
        with patch("subprocess.Popen", side_effect=AssertionError("Unexpected subprocess")):
            self.assertEqual(self.invoke(self.arguments())[0], 0)
            self.assertEqual(self.invoke(self.arguments("deploy"))[0], 3)

    def test_module_entry_point_from_empty_directory(self):
        root = str(Path(__file__).resolve().parents[1])
        environment = dict(os.environ, PYTHONPATH=root, PYTHONDONTWRITEBYTECODE="1")
        with tempfile.TemporaryDirectory() as directory:
            for arguments, expected in ((self.arguments(), 0), (self.arguments("deploy"), 3)):
                result = subprocess.run(
                    [sys.executable, "-B", "-m", "toolkit", *arguments],
                    cwd=directory, env=environment, capture_output=True, text=True, timeout=10,
                )
                self.assertEqual(result.returncode, expected, result.stderr)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_preflight_pass_is_only_a_snapshot(self):
        with patch("toolkit.cli.inspect_preflight", return_value={"candidate_image_id": "sha256:" + "a" * 64,
                                                                "current_image_id": "sha256:" + "b" * 64}):
            code, output, error = self.invoke(self.arguments("preflight"))
        self.assertEqual(code, 0)
        self.assertIn("READ-ONLY SNAPSHOT", output)

    def test_preflight_and_status_failures_are_nonzero(self):
        from toolkit.docker import InspectionError
        for command, target in (("preflight", "inspect_preflight"), ("status", "inspect_status")):
            with patch("toolkit.cli." + target, side_effect=InspectionError("Inspection unavailable")):
                arguments = ["status"] if command == "status" else self.arguments(command)
                self.assertEqual(self.invoke(arguments)[0], 4)


class ConfigurationTests(unittest.TestCase):
    def test_defaults_match_demo(self):
        settings = Settings()
        self.assertEqual(settings.project, "sdt-demo")
        self.assertEqual(settings.service, "api")
        self.assertEqual(settings.direct_url, "http://127.0.0.1:8089")
        self.assertEqual(settings.proxy_url, "http://127.0.0.1:8088")

    def test_supported_image_forms(self):
        for value in ("sdt-demo-api:phase1", "localhost:5000/demo:v1", "sha256:" + "a" * 64,
                      "example/demo@sha256:" + "b" * 64):
            with self.subTest(value=value):
                self.assertEqual(validate_image(value), value)

    def test_unsupported_image_inputs(self):
        for value in ("", "demo", "localhost:5000/demo", "-v1", "a:v1\n", "a:v1;pwd",
                      "a:v1 b:v2", "sha256:abc", "a@sha256:abc", "a:", "a//b:v1", "a" * 256):
            with self.subTest(value=value):
                with self.assertRaises(ConfigurationError):
                    validate_image(value)

    def test_release_boundaries(self):
        for value in ("demo-v1", "v1.0_test", "a" * 64):
            self.assertEqual(validate_release(value), value)
        for value in ("", "a" * 65, "-v1", "v1\n", "hello world", "v1/2"):
            with self.subTest(value=value):
                with self.assertRaises(ConfigurationError):
                    validate_release(value)

    def test_timeout_ranges_and_types(self):
        for name, maximum in (("verification_timeout", 600), ("request_timeout", 30),
                              ("retry_interval", 30), ("command_timeout", 300)):
            for value in (0, -1, maximum + 1, True, 1.5, float("nan"), float("inf")):
                with self.subTest(name=name, value=value):
                    with self.assertRaises(ConfigurationError):
                        Settings(**{name: value})

    def test_inconsistent_deadlines_are_rejected(self):
        for settings in ({"verification_timeout": 2, "request_timeout": 3},
                         {"verification_timeout": 3, "retry_interval": 3}):
            with self.assertRaises(ConfigurationError):
                Settings(**settings)


if __name__ == "__main__":
    unittest.main()
