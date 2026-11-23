import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from test_recovery import IMAGE, OTHER, RecoveryFixture, SECRET
from toolkit.checks import verify
from toolkit.cli import main
from toolkit.deploy import deploy
from toolkit.processes import CommandError
from toolkit.reconcile import reconcile
from toolkit.state import MAX_RECORD_BYTES, RecordError, operation_session, read_state


class ReportTests(RecoveryFixture):
    def failure(self, request, *args, **kwargs):
        tick = [0]

        def sleep(seconds):
            tick[0] += seconds

        def observe(url, kind, *unused):
            if kind == "release":
                return "unexpected-body"
            return "ok"

        duration = kwargs.pop("duration", 2)
        return verify(request, *args, **kwargs, duration=duration,
                      clock=lambda: tick[0], sleep=sleep, http=observe)

    def load(self, record):
        return json.loads((self.root / "reports" / f"operation-{record['id']}.json").read_bytes())

    def test_known_failure_persists_evidence_and_keeps_prior_success(self):
        target = self.baseline()
        self.verify.side_effect = self.failure
        self.assertEqual(deploy(self.request, self.root), 1)
        state = read_state(self.root)
        record = state["latest"]
        self.assertEqual(state["version"], 5)
        self.assertEqual(state["last_success"]["id"], target)
        self.assertLessEqual((self.directory / "state.json").stat().st_size, MAX_RECORD_BYTES)
        report = self.load(record)
        self.assertEqual(report["operation"]["verification"], record["verification_trace"])
        self.assertEqual(report["operation"]["outcome"], "failed")
        self.assertIsNone(report["automatic_recovery"])
        self.assertEqual(record["verification_trace"]["first_failed"]["routes"]["direct_version"], "unexpected-body")
        self.assertEqual(record["verification_trace"]["last"]["instance"]["image_id"], IMAGE)
        self.assertFalse(record["checks"]["identity"])
        self.run.assert_not_called()

    def test_on_demand_success_uses_only_safe_fields_and_never_calls_docker(self):
        op = self.baseline()
        record = read_state(self.root)["latest"]
        before = (self.directory / "state.json").read_bytes()
        self.assertFalse((self.root / "reports").exists())
        with patch("toolkit.deploy.Docker", side_effect=AssertionError):
            self.assertEqual(main(["report", "--operation", op]), 0)
        report = self.load(record)
        self.assertIsNone(report["operation"]["verification"])
        self.assertTrue(all(report["operation"]["checks"].values()))
        text = json.dumps(report)
        for private in (SECRET, "signature", "snapshot", "environment", str(self.root), "demo-v1"):
            self.assertNotIn(private, text)
        self.assertEqual(before, (self.directory / "state.json").read_bytes())

    def test_unknown_id_and_busy_journal(self):
        missing = "0" * 32
        self.assertEqual(main(["report", "--operation", missing]), 2)
        self.assertFalse(self.directory.exists())
        op = self.baseline()
        self.assertEqual(main(["report", "--operation", missing]), 2)
        with operation_session(self.root):
            self.assertEqual(main(["report", "--operation", op]), 5)
        self.assertFalse((self.root / "reports").exists())

    def test_corrupt_trace_refuses_regeneration(self):
        self.verify.side_effect = self.failure
        self.assertEqual(deploy(self.request, self.root), 1)
        state = read_state(self.root)
        latest = state["latest"]
        old_report = self.load(latest)
        latest["verification_trace"]["last"]["routes"]["live"] = SECRET
        (self.directory / "state.json").write_text(json.dumps(state))
        self.assertEqual(main(["report", "--operation", latest["id"]]), 6)
        self.assertEqual(self.load(latest), old_report)

    def test_report_directory_symlink_is_refused(self):
        op = self.baseline()
        with tempfile.TemporaryDirectory() as outside:
            (self.root / "reports").symlink_to(outside, target_is_directory=True)
            self.assertEqual(main(["report", "--operation", op]), 7)
            self.assertEqual(list(Path(outside).iterdir()), [])

    def test_observation_after_unconfirmed_command_stays_pending_until_closure(self):
        self.baseline()
        # Request the available image via a stopped API to force replacement.
        self.api["State"].update(Status="exited", Running=False)
        self.docker.network["Containers"].pop(self.api["Id"])
        self.run.side_effect = CommandError("private command error")
        self.verify.side_effect = self.failure
        self.assertEqual(deploy(self.request, self.root), 6)
        record = read_state(self.root)["latest"]
        self.assertIsNone(record["checks"])
        self.assertEqual(self.load(record)["operation"]["outcome"], "pending")
        self.assertIsNotNone(self.load(record)["operation"]["verification"])
        self.assertEqual(self.run.call_count, 1)
        with patch("toolkit.reconcile.Docker", return_value=self.docker):
            self.assertEqual(reconcile(record["id"], close=True), 0)
        updated = self.load(record)["operation"]
        self.assertEqual(updated["outcome"], "closed-unknown")
        self.assertEqual(updated["verification"], record["verification_trace"])
        self.assertEqual(updated["reconciliation"]["image_id"], IMAGE)

    def test_legacy_record_can_be_exported_without_inventing_evidence(self):
        with operation_session(self.root) as journal:
            op = journal.begin(IMAGE, "old-release")
            journal.finish(op, "failed")
        self.assertEqual(main(["report", "--operation", op]), 0)
        report = self.load(read_state(self.root)["latest"])["operation"]
        self.assertIsNone(report["checks"])
        self.assertIsNone(report["verification"])

    def test_oversized_snapshot_leaves_previous_state_readable(self):
        op = self.baseline()
        before = (self.directory / "state.json").read_bytes()
        with operation_session(self.root) as journal, patch("toolkit.state.MAX_RECORD_BYTES", 512):
            with self.assertRaises(RecordError):
                journal.begin(OTHER, "demo-v2", action="replace")
        self.assertEqual((self.directory / "state.json").read_bytes(), before)
        self.assertEqual(read_state(self.root)["latest"]["id"], op)
