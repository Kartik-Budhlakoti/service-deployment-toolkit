from contextlib import redirect_stdout
from copy import deepcopy
from importlib import import_module
import io
import unittest
from unittest.mock import patch

from toolkit.locking import LockBusy
from toolkit.state import StateUncertain

driver = import_module("scripts.phase4-acceptance")


class OutageTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(redirect_stdout(io.StringIO()))
        self.calls = self.enterContext(patch.object(driver.subprocess, "run"))
        self.enterContext(patch.object(driver, "Docker"))
        self.session = self.enterContext(patch.object(driver, "operation_session"))
        self.enterContext(patch.object(driver, "read_state", return_value={"latest": None}))
        self.before = {"api_id": "1" * 64, "dependency_ids": {"db": "2" * 64, "nginx": "3" * 64}}
        self.enterContext(patch.object(driver, "healthy", return_value=self.before))
        self.inspect = self.enterContext(patch.object(driver, "inspect_preflight", return_value=self.before))
        self.outage_rows = {}
        self.diagnose = self.enterContext(patch.object(driver, "diagnostics", side_effect=self.diagnostic_rows))

    def diagnostic_rows(self, expected):
        if expected == 1:
            return self.outage_rows
        return dict.fromkeys((driver.DNS, driver.TCP, driver.DIRECT, driver.PROXY), "ok")

    def commands(self):
        return [call.args[0] for call in self.calls.call_args_list]

    def test_proxy_outage_only_touches_original_proxy(self):
        self.outage_rows = {driver.DNS: "ok", driver.TCP: "ok", driver.DIRECT: "ok",
                                      driver.PROXY: "skipped-container-exited"}
        driver.dependency_outage("nginx")
        proxy = self.before["dependency_ids"]["nginx"]
        self.assertEqual([args[-2:] for args in self.commands()], [["stop", proxy], ["start", proxy], [driver.sys.executable, "tests/smoke.py"]])

    def test_database_outage_needs_an_independent_smoke_check(self):
        self.outage_rows = {driver.DNS: "resolution-failed", driver.TCP: "skipped-no-running-db-address",
                                      driver.DIRECT: "probe-unavailable", driver.PROXY: "http-503"}
        driver.dependency_outage("db")
        db = self.before["dependency_ids"]["db"]
        self.assertEqual([args[-2:] for args in self.commands()],
                         [["stop", db], ["tests/smoke.py", "--database-down"], ["start", db], [driver.sys.executable, "tests/smoke.py"]])

    def test_unexpected_outage_or_interrupt_starts_original_container(self):
        for failure in (driver.ExerciseFailed("no evidence"), KeyboardInterrupt()):
            with self.subTest(error=type(failure)):
                self.calls.reset_mock()
                self.diagnose.side_effect = [failure, self.diagnostic_rows(0)]
                with self.assertRaises(type(failure)):
                    driver.dependency_outage("db")
                self.assertEqual(self.commands()[1][-2:], ["start", self.before["dependency_ids"]["db"]])

    def test_ownership_change_lock_or_pending_state_prevents_stop(self):
        for failure in (LockBusy(), StateUncertain()):
            self.session.side_effect = failure
            with self.assertRaises(type(failure)):
                driver.dependency_outage("nginx")
        self.session.side_effect = None
        self.inspect.return_value = dict(self.before, api_id="9" * 64)
        with self.assertRaises(driver.ExerciseFailed):
            driver.dependency_outage("nginx")
        self.calls.assert_not_called()

    def test_changed_dependency_after_start_prevents_pass(self):
        self.inspect.side_effect = [self.before, dict(self.before, dependency_ids={})]
        self.outage_rows = {driver.DNS: "ok", driver.TCP: "ok", driver.DIRECT: "ok",
                                      driver.PROXY: "skipped-container-exited"}
        with self.assertRaises(driver.ExerciseFailed):
            driver.dependency_outage("nginx")

    def test_rejects_misleading_route_combinations(self):
        cases = [
            ("db", {driver.DNS: "resolution-failed", driver.TCP: "skipped-no-running-db-address",
                    driver.DIRECT: "ok", driver.PROXY: "http-503"}),
            ("nginx", {driver.DNS: "ok", driver.TCP: "ok", driver.DIRECT: "probe-unavailable",
                       driver.PROXY: "skipped-container-exited"}),
        ]
        for service, rows in cases:
            with self.subTest(service=service), self.assertRaises(driver.ExerciseFailed):
                driver.expect_outage(service, rows)


class IncidentTests(unittest.TestCase):
    def setUp(self):
        first = {"instance": {"image_id": "candidate"}}
        trace = {"first_failed": first, "last": {"instance": None}}
        self.failed = dict(id="a", status="failed", image_id="candidate", checks={"container": False},
                           verification_trace=trace)
        self.recovered = dict(id="b", status="succeeded", image_id="original", checks={"container": True},
                              recovery={"kind": "automatic", "trigger": "a", "target": "baseline"})
        self.report = {
            "version": 1,
            "operation": dict(id="a", outcome="failed", image_id="candidate", checks={"container": False},
                              verification=deepcopy(trace), automatic_target="baseline"),
            "automatic_recovery": dict(id="b", outcome="succeeded", image_id="original",
                                       checks={"container": True}, recovery_request=deepcopy(self.recovered["recovery"])),
        }

    def test_accepts_distinct_outcomes_when_final_sample_has_no_identity(self):
        driver.check_report(self.report, self.failed, self.recovered)

    def test_rejects_missing_evidence_wrong_link_and_swapped_image(self):
        for section, key, bad in (("operation", "verification", None),
                                  ("operation", "image_id", "original"),
                                  ("automatic_recovery", "recovery_request", {"trigger": "another"}),
                                  ("automatic_recovery", "outcome", "pending")):
            report = deepcopy(self.report)
            report[section][key] = bad
            with self.subTest(key=key), self.assertRaises(driver.ExerciseFailed):
                driver.check_report(report, self.failed, self.recovered)
