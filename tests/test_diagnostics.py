import io
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
import socket
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

from test_preflight import FakeDocker
from toolkit.cli import main
from toolkit.diagnostics import DiagnosticDocker, collect, snapshot
from toolkit.docker import InspectionError
from toolkit.network_probe import probe
from toolkit.preflight import LABEL, NETWORK, check_resources


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.docker = FakeDocker(self.root)
        self.docker.root = self.root
        for i, item in enumerate(self.docker.items, start=2):
            item["State"]["StartedAt"] = "start"
            item["NetworkSettings"]["Networks"][NETWORK]["IPAddress"] = f"172.18.0.{i}"

    def stop(self, name):
        item = next(item for item in self.docker.items if item["Config"]["Labels"][LABEL + "service"] == name)
        item["State"].update(Status="exited", Running=False)
        self.docker.network["Containers"].pop(item["Id"])

    def run_cli(self, network="ok", http="ok"):
        original = self.docker.text
        def text(*args):
            if args[0] == "exec":
                self.assertEqual(args[1], self.docker.items[0]["Id"])
                return network
            return original(*args)
        output = io.StringIO()
        with (patch("toolkit.diagnostics.Path.cwd", return_value=self.root),
              patch("toolkit.diagnostics.DiagnosticDocker", return_value=self.docker),
              patch.object(self.docker, "text", side_effect=text),
              patch("toolkit.diagnostics.run_command", return_value=http),
              redirect_stdout(output), redirect_stderr(output)):
            status = main(["diagnose"])
        self.assertFalse((self.root / ".runtime").exists())
        return status, output.getvalue()

    def test_healthy_stack(self):
        code, output = self.run_cli()
        self.assertEqual(code, 0)
        self.assertEqual(output.count(": ok ("), 4)

    def test_exited_api_skips_inside_and_direct_probes(self):
        self.stop("api")
        code, output = self.run_cli(http="http-502")
        self.assertEqual(code, 1)
        self.assertEqual(output.count("skipped-container-exited"), 3)
        self.assertIn("nginx (/items): http-502", output)

    def test_stopped_dependencies_are_only_accepted_for_diagnostics(self):
        for name in ("db", "nginx"):
            self.stop(name)
        with self.assertRaises(InspectionError):
            check_resources(self.docker.items, self.root)
        code, output = self.run_cli(network="resolution-failed", http="http-503")
        self.assertEqual(code, 1)
        for outcome in ("resolution-failed", "skipped-no-running-db-address", "http-503", "skipped-container-exited"):
            self.assertIn(outcome, output)

    def test_unrecognized_output_is_withheld(self):
        code, output = self.run_cli(network="private-value", http="private-value")
        self.assertEqual(code, 1)
        self.assertEqual(output.count("probe-unavailable"), 4)
        self.assertNotIn("private-value", output)

    def test_foreign_checkout_or_extra_network_member_refused(self):
        self.docker.network["Containers"]["foreign"] = {}
        self.assertEqual(self.run_cli()[0], 4)
        del self.docker.network["Containers"]["foreign"]
        self.docker.items[0]["Config"]["Labels"][LABEL + "project.working_dir"] = "/other"
        code, output = self.run_cli()
        self.assertEqual(code, 4)
        self.assertNotIn("api -> db", output)

    def test_changed_snapshot_is_incomplete(self):
        original = snapshot(self.docker, self.root)
        with patch("toolkit.diagnostics.snapshot", side_effect=[original, {}]):
            self.assertEqual(self.run_cli()[0], 4)

    def test_expired_budget_skips_probes(self):
        services = snapshot(self.docker, self.root)
        with (patch.object(self.docker, "text", side_effect=AssertionError),
              patch("toolkit.diagnostics.run_command", side_effect=AssertionError)):
            rows = collect(self.docker, services, time.monotonic() - 1)
        self.assertEqual([row.outcome for row in rows], ["skipped-deadline"] * 4)

    def test_expired_budget_does_not_spawn_docker(self):
        with patch("toolkit.docker.run_command", side_effect=AssertionError):
            with self.assertRaises(InspectionError):
                DiagnosticDocker(self.root, time.monotonic() - 1).connect()


class NetworkWorkerTests(unittest.TestCase):
    def test_dns_checks_owned_database_address(self):
        row = (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("172.18.0.3", 5432))
        with patch("socket.getaddrinfo", return_value=[row]):
            self.assertEqual(probe("dns", "172.18.0.3", 1), "ok")
            self.assertEqual(probe("dns", "172.18.0.4", 1), "unexpected-address")
            self.assertEqual(probe("dns", "", 1), "resolved-address-unconfirmed")
        with patch("socket.getaddrinfo", side_effect=socket.gaierror):
            self.assertEqual(probe("dns", "", 1), "resolution-failed")

    def test_tcp_targets_owned_address_even_when_dns_is_unavailable(self):
        client = MagicMock()
        with patch("socket.socket") as factory, patch("socket.getaddrinfo", side_effect=AssertionError):
            factory.return_value.__enter__.return_value = client
            self.assertEqual(probe("tcp", "172.18.0.3", 1), "ok")
            client.connect.assert_called_once_with(("172.18.0.3", 5432))
            for error, expected in ((ConnectionRefusedError, "connection-refused"), (TimeoutError, "timeout")):
                client.connect.side_effect = error
                self.assertEqual(probe("tcp", "172.18.0.3", 1), expected)
