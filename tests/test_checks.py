import io
import json
from pathlib import Path
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
import unittest
from unittest.mock import MagicMock, patch

from toolkit.checks import http_check, http_observation, verify
from toolkit.config import DeploymentRequest, Settings
from toolkit.http_probe import ITEMS, observe_http, probe


IMAGE = 'sha256:' + 'a'*64


class CheckTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.request = DeploymentRequest(IMAGE, 'demo-v1', Settings(verification_timeout=4, request_timeout=1))
        self.api = {'Id': '1'*64, 'Image': IMAGE, 'State': {'Running': True}, 'RestartCount': 0}
        self.rows = {'api': self.api, 'db': {'Id': '2'*64}, 'nginx': {'Id': '3'*64}}
        self.deps = {name: self.rows[name]['Id'] for name in ('db', 'nginx')}
        self.http_calls = []
        self.mock = patch('toolkit.checks.check_resources', side_effect=lambda *args: self.rows)
        self.mock.start(); self.addCleanup(self.mock.stop)
        self.list_mock = patch('toolkit.checks.containers', return_value=[])
        self.list_mock.start(); self.addCleanup(self.list_mock.stop)

    def sleep(self, seconds):
        self.now += seconds

    def http(self, url, kind, release, timeout):
        self.http_calls.append((url, kind, timeout))
        return True

    def run_check(self, http=None, *, expected_api=None):
        return verify(self.request, Path('/tmp'), object(), IMAGE, self.deps,
                      clock=lambda: self.now, sleep=self.sleep, http=http or self.http,
                      expected_api=expected_api)

    def test_all_five_groups_must_pass_in_same_attempt(self):
        result = self.run_check()
        self.assertTrue(result.passed)
        self.assertEqual(len(result.checks), 5)
        self.assertEqual(len(self.http_calls), 5)
        self.assertEqual(result.attempts, 1)

    def test_wrong_image_fails_identity(self):
        self.api['Image'] = 'sha256:' + 'b'*64
        result = self.run_check()
        self.assertFalse(result.passed)
        self.assertFalse(result.checks['identity'])
        self.assertEqual(self.now, 4)

    def test_proxy_failure_prevents_success(self):
        result = self.run_check(lambda url, *args: ':8088' not in url)
        self.assertFalse(result.passed)
        self.assertFalse(result.checks['proxy'])

    def test_dependency_replacement_is_not_success(self):
        self.rows['db']['Id'] = 'f'*64
        self.assertFalse(self.run_check().passed)
        self.assertEqual(self.http_calls, [])

    def test_probes_cannot_pass_for_a_different_process_start(self):
        self.api["State"]["StartedAt"] = "after"
        self.assertFalse(self.run_check(expected_api=(self.api["Id"], "before")).passed)
        self.assertEqual(self.http_calls, [])

    def test_restart_during_cycle_invalidates_that_cycle(self):
        def http(*args):
            self.rows = dict(self.rows, api=dict(self.api, RestartCount=1))
            return True
        # Every start sees count 0; every end sees count 1.
        values = []
        for _ in range(4):
            values.extend([dict(self.rows, api=dict(self.api)),
                           dict(self.rows, api=dict(self.api, RestartCount=1))])
        with patch('toolkit.checks.check_resources', side_effect=values):
            self.assertFalse(self.run_check().passed)

    def test_work_is_capped_to_shared_deadline(self):
        budgets = []
        def http(url, kind, release, timeout):
            budgets.append(timeout)
            self.now += timeout
            return False
        result = self.run_check(http)
        self.assertFalse(result.passed)
        self.assertEqual(sum(budgets), 4)
        self.assertEqual(self.now, 4)

    def test_late_pass_is_rejected(self):
        def http(*args):
            self.now += 2
            return True
        self.assertFalse(self.run_check(http).passed)

    def test_first_failure_and_last_sample_keep_separate_route_results(self):
        self.api["State"]["StartedAt"] = "2026-11-22T07:09:43.759178212Z"
        def responses(url, kind, *unused):
            if kind == "items" and ":8088" in url:
                return "http-503" if self.now == 0 else "connection-refused"
            return "ok"
        result = self.run_check(responses)
        first, last = result.trace["first_failed"], result.trace["last"]
        self.assertEqual((first["number"], last["number"]), (1, 4))
        self.assertEqual(first["routes"]["proxy_items"], "http-503")
        self.assertEqual(last["routes"]["proxy_items"], "connection-refused")
        self.assertEqual(last["routes"]["direct_items"], "ok")
        self.assertEqual(first["instance"], {"api_id": self.api["Id"], "image_id": IMAGE,
                                            "started_at": self.api["State"]["StartedAt"]})
        self.assertEqual(last["inspection"], "running")

    def test_skipped_probes_and_unknown_worker_text_are_distinct(self):
        self.rows["db"]["Id"] = "f" * 64
        sample = self.run_check().trace["last"]
        self.assertIsNone(sample["instance"])
        self.assertEqual(set(sample["routes"].values()), {"not-run"})
        self.assertEqual(sample["inspection"], "unconfirmed")
        self.rows["db"]["Id"] = self.deps["db"]
        def over_budget(*args):
            self.now += 5
            return "private driver message"
        sample = self.run_check(over_budget).trace["last"]
        self.assertTrue(sample["deadline"])
        self.assertEqual(sample["routes"]["live"], "probe-unavailable")
        self.assertEqual(sample["routes"]["direct_items"], "deadline")


class HTTPProbeTests(unittest.TestCase):
    def setUp(self):
        self.payload = b'{"status":"alive"}'
        self.status = 200
        self.delay = 0
        self.location = '/other'
        case = self
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                time.sleep(case.delay)
                self.send_response(case.status)
                if case.status == 302:
                    self.send_header('Location', case.location)
                self.send_header('Content-Length', str(len(case.payload)))
                self.end_headers()
                try:
                    self.wfile.write(case.payload)
                except (BrokenPipeError, ConnectionResetError):
                    pass
            def log_message(self, *args):
                pass
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.url = f'http://127.0.0.1:{self.server.server_port}/health/live'

    def test_real_worker_success(self):
        self.assertTrue(http_check(self.url, 'live', 'demo-v1', 2))

    def test_real_worker_returns_only_safe_failure_detail(self):
        self.status, self.payload = 503, b'private fixture text'
        self.assertEqual(http_observation(self.url, 'items', '', 2), 'http-503')

    def test_wrong_status_body_and_malformed_json_fail(self):
        for status, body in ((503,b'{}'), (200,b'{'), (200,b'{"status":"wrong"}')):
            with self.subTest(status=status, body=body):
                self.status, self.payload = status, body
                self.assertFalse(probe(self.url, 'live', 'demo-v1', 1))

    def test_diagnostic_http_details(self):
        for status, body, outcome in ((503, b'private fixture', 'http-503'),
                                      (200, b'{}', 'unexpected-body'),
                                      (200, b'{', 'invalid-body'),
                                      (200, b'x' * 65537, 'oversize-body')):
            with self.subTest(outcome=outcome):
                self.status, self.payload = status, body
                self.assertEqual(observe_http(self.url, 'items', '', 2), outcome)

    def test_redirect_is_not_followed(self):
        self.status = 302
        self.assertFalse(probe(self.url, 'live', 'demo-v1', 1))

    def test_response_size_limit(self):
        self.payload = b' ' * 65537
        self.assertFalse(probe(self.url, 'live', 'demo-v1', 1))

    def test_boolean_id_is_not_integer_fixture(self):
        rows = [dict(row) for row in ITEMS]
        rows[0]['id'] = True
        self.payload = json.dumps(rows).encode()
        self.assertFalse(probe(self.url, 'items', 'demo-v1', 1))

    def test_stalled_response_is_bounded_by_parent(self):
        self.delay = 2
        before = time.monotonic()
        self.assertFalse(http_check(self.url, 'live', 'demo-v1', 0.15))
        self.assertLess(time.monotonic() - before, 1.5)

    def test_release_and_catalogue_content(self):
        self.payload = b'{"release":"demo-v1"}'
        self.assertTrue(probe(self.url, 'release', 'demo-v1', 1))
        self.assertFalse(probe(self.url, 'release', 'other', 1))
        self.payload = json.dumps(ITEMS).encode()
        self.assertTrue(probe(self.url, 'items', 'demo-v1', 1))


class HTTPErrorCleanupTests(unittest.TestCase):
    def test_rejected_http_responses_are_closed(self):
        for status in (302, 503):
            with self.subTest(status=status):
                body = io.BytesIO(b'{}')
                error = HTTPError('http://127.0.0.1/probe', status,
                                  'Test response', {}, body)
                self.addCleanup(error.close)
                opener = MagicMock()
                opener.open.side_effect = error
                with patch('toolkit.http_probe.build_opener', return_value=opener):
                    self.assertFalse(probe('http://127.0.0.1/probe', 'live', 'demo-v1', 1))
                self.assertTrue(body.closed)
                self.assertTrue(error.closed)
