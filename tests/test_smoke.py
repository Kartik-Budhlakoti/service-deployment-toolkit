from http.server import BaseHTTPRequestHandler, HTTPServer
import importlib.util
from pathlib import Path
from threading import Thread
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("smoke_checker", Path(__file__).with_name("smoke.py"))
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class SmokeCheckerTests(unittest.TestCase):
    def setUp(self):
        output = patch.object(smoke, "print", create=True)
        output.start()
        self.addCleanup(output.stop)

    def test_healthy_mode_executes_all_four_requests(self):
        responses = [(200, {"status": "alive"}), (200, {"release": "demo-v1"}),
                     (200, {"status": "ready"}), (200, smoke.EXPECTED)]
        with patch.object(smoke, "read", side_effect=responses) as read:
            smoke.verify("http://example.invalid")
        self.assertEqual(read.call_count, 4)

    def test_outage_mode_executes_all_four_requests(self):
        responses = [(200, {"status": "alive"}), (200, {"release": "demo-v1"}),
                     (503, {"detail": "Catalogue unavailable"}),
                     (503, {"detail": "Catalogue unavailable"})]
        with patch.object(smoke, "read", side_effect=responses) as read:
            smoke.verify("http://example.invalid", database_down=True)
        self.assertEqual(read.call_count, 4)

    def test_redirect_cannot_substitute_another_route(self):
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(self.path)
                if self.path == "/health/live":
                    self.send_response(302)
                    self.send_header("Location", "/other")
                    self.end_headers()
                else:
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b'{"status":"alive"}')

            def log_message(self, *args):
                pass

        with HTTPServer(("127.0.0.1", 0), Handler) as server:
            worker = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02})
            worker.start()
            try:
                with self.assertRaisesRegex(smoke.CheckFailure, "302"):
                    smoke.read(f"http://127.0.0.1:{server.server_port}/health/live")
            finally:
                server.shutdown()
                worker.join()
        self.assertEqual(requests, ["/health/live"])

    def test_catalogue_ids_must_be_json_integers(self):
        for wrong in (True, 1.0):
            items = [dict(smoke.EXPECTED[0], id=wrong), *smoke.EXPECTED[1:]]
            responses = [(200, {"status": "alive"}), (200, {"release": "demo-v1"}),
                         (200, {"status": "ready"}), (200, items)]
            with self.subTest(wrong=wrong), patch.object(smoke, "read", side_effect=responses):
                with self.assertRaisesRegex(smoke.CheckFailure, "integer"):
                    smoke.verify("http://example.invalid")

    def test_wrong_status_fails(self):
        with patch.object(smoke, "read", return_value=(503, {"status": "alive"})):
            with self.assertRaises(smoke.CheckFailure):
                smoke.verify("http://example.invalid")

    def test_wrong_content_fails(self):
        with patch.object(smoke, "read", return_value=(200, {"status": "wrong"})):
            with self.assertRaises(smoke.CheckFailure):
                smoke.verify("http://example.invalid")

    def test_connection_failure_makes_command_fail(self):
        with patch.object(smoke, "read", side_effect=ConnectionRefusedError), \
                patch("sys.argv", ["smoke.py"]):
            self.assertEqual(smoke.main(), 1)


if __name__ == "__main__":
    unittest.main()
