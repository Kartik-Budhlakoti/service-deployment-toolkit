import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from toolkit.docker import Docker, InspectionError


class DockerRunnerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.executable = self.root / "docker"
        environment = patch.dict(os.environ, {"PATH": str(self.root)}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        self.docker = Docker(self.root, timeout=2)

    def program(self, body):
        import sys
        self.executable.write_text("#!" + sys.executable + "\n" + body)
        self.executable.chmod(0o700)

    def test_json_and_explicit_context(self):
        self.program("import json, sys\nprint(json.dumps(sys.argv[1:]))\n")
        self.assertEqual(self.docker.json("info"), ["--context", "default", "info"])

    def test_failure_does_not_echo_raw_secrets(self):
        self.program("import sys\nprint('private-fixture-value', file=sys.stderr)\nsys.exit(1)\n")
        with self.assertRaises(InspectionError) as error:
            self.docker.text("info")
        self.assertNotIn("private-fixture-value", str(error.exception))

    def test_malformed_json(self):
        self.program("print('not-json')\n")
        with self.assertRaises(InspectionError):
            self.docker.json("info")

    def test_missing_executable(self):
        with self.assertRaises(InspectionError):
            self.docker.text("info")

    def test_deadline(self):
        self.program("import time\ntime.sleep(5)\n")
        self.docker.timeout = 0.05
        with self.assertRaisesRegex(InspectionError, "timed out"):
            self.docker.text("info")

    def test_output_limit_includes_stderr(self):
        self.program("import sys\nsys.stderr.write('x' * (1024 * 1024 + 1))\n")
        with self.assertRaisesRegex(InspectionError, "limit"):
            self.docker.text("info")

    def run_descendant_case(self, parent_action, expected_error):
        import signal
        import time
        pid_path = self.root / "child.pid"
        child = "import time; time.sleep(30)"
        self.program(
            "import os, subprocess, sys, time\n"
            "from pathlib import Path\n"
            f"child = subprocess.Popen([sys.executable, '-c', {child!r}])\n"
            f"Path({str(pid_path)!r}).write_text(str(child.pid))\n"
            + parent_action + "\n"
        )
        self.docker.timeout = 1
        try:
            with self.assertRaisesRegex(InspectionError, expected_error):
                self.docker.text("info")
            self.assertTrue(pid_path.exists(), "Fake Docker did not start its child")
            pid = int(pid_path.read_text())
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                try:
                    status = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
                except (FileNotFoundError, ProcessLookupError):
                    return
                if status == "Z":  # Exited; its new parent may not have reaped it yet.
                    return
                time.sleep(0.01)
            self.fail("The child was still executing after runner cleanup")
        finally:
            if pid_path.exists():
                try:
                    os.kill(int(pid_path.read_text()), signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def test_timeout_stops_parent_and_child_group(self):
        self.run_descendant_case("time.sleep(30)", "timed out")

    def test_timeout_stops_child_even_after_parent_exits(self):
        self.run_descendant_case("os._exit(0)", "timed out")

    def test_output_limit_stops_child_group(self):
        self.run_descendant_case("sys.stderr.write('x' * (1024 * 1024 + 1)); sys.stderr.flush(); time.sleep(30)", "limit")

    def test_remote_environment_override_refused(self):
        with patch.dict(os.environ, {"DOCKER_HOST": "tcp://example.invalid:2375"}):
            with self.assertRaises(InspectionError):
                Docker(self.root)

    def test_wrong_context_and_endpoint_refused(self):
        with patch.object(self.docker, "_run", return_value="desktop-linux"):
            with self.assertRaises(InspectionError):
                self.docker.connect()
        with patch.object(self.docker, "_run", return_value="default"), patch.object(self.docker, "json", return_value=[
            {"Endpoints": {"docker": {"Host": "tcp://example.invalid:2375"}}}
        ]):
            with self.assertRaises(InspectionError):
                self.docker.connect()

    def test_supported_context_and_daemon(self):
        with patch.object(self.docker, "_run", return_value="default"), patch.object(self.docker, "json", side_effect=[
            [{"Endpoints": {"docker": {"Host": "unix:///var/run/docker.sock"}}}],
            {"OSType": "linux", "Architecture": "x86_64"},
        ]):
            self.assertEqual(self.docker.connect()["OSType"], "linux")

    def test_config_inspection_includes_profiled_services(self):
        self.program(
            "import json, sys\n"
            "args = sys.argv[1:]\n"
            "services = ['api', 'db', 'nginx']\n"
            "if '--profile' in args and args[args.index('--profile') + 1] == '*':\n"
            "    services.append('init')\n"
            "print(json.dumps({'services': services, 'arguments': args}))\n"
        )
        result = self.docker.compose("config", "--format", "json")
        self.assertEqual(set(result["services"]), {"api", "db", "nginx", "init"})
        self.assertEqual(result["arguments"][-5:], ["--profile", "*", "config", "--format", "json"])

    def test_config_helper_refuses_mutation_commands(self):
        with patch.object(self.docker, "json") as query:
            for arguments in (("up", "-d"), ("run", "init"), ("down",)):
                with self.assertRaises(InspectionError):
                    self.docker.compose(*arguments)
            query.assert_not_called()


if __name__ == "__main__":
    unittest.main()
