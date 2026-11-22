import json
from unittest.mock import patch

from test_recovery import IMAGE, OTHER, RecoveryFixture
from toolkit.cli import main
from toolkit.config import ExitCode
from toolkit.deploy import deploy
from toolkit.override import read_override, write_override
from toolkit.preflight import LABEL
from toolkit.reconcile import observe_pending, reconcile
from toolkit.recovery import history, read_only
from toolkit.state import CLOSED_UNKNOWN, OperationJournal, RecordError, operation_session, read_state


class ReconciliationTests(RecoveryFixture):
    def setUp(self):
        super().setUp()
        self.enterContext(patch("toolkit.reconcile.Docker", return_value=self.docker))

    def pending(self, *, override=None, action="replace"):
        with operation_session(self.root) as journal:
            operation = journal.begin(OTHER, "demo-v2", action=action)
            if override:
                write_override(self.root, override)
                self.replace_api(IMAGE)
        return operation

    def test_preview_creates_no_journal_or_key(self):
        self.assertEqual(reconcile("f" * 32), ExitCode.STATE_UNCERTAIN)
        self.assertFalse(self.directory.exists())
        operation = self.pending(override=OTHER)
        self.assertFalse((self.directory / "recovery.key").exists())
        recorded = {p.name: p.read_bytes() for p in self.directory.iterdir()}
        self.assertEqual(main(["reconcile", "--operation", operation]), ExitCode.OK)
        self.assertEqual(recorded, {p.name: p.read_bytes() for p in self.directory.iterdir()})
        self.assertIn("would align it", self.out.getvalue())
        self.run.assert_not_called()

    def test_closure_preserves_prior_success_and_repairs_only_pending_override(self):
        target = self.baseline()
        operation = self.pending(override=OTHER)
        self.assertEqual(deploy(self.request, self.root), ExitCode.STATE_UNCERTAIN)
        prior = read_state(self.root)["last_success"]
        api = self.api["Id"]
        self.assertEqual(main(["reconcile", "--operation", operation, "--close-unknown"]), ExitCode.OK)
        state = read_state(self.root)
        closed = state["latest"]
        self.assertEqual(state["version"], 4)
        self.assertEqual(closed["status"], CLOSED_UNKNOWN)
        self.assertEqual(closed["id"], operation)
        self.assertEqual(closed["image_id"], OTHER)
        self.assertIsNone(closed["checks"])
        self.assertEqual(closed["reconciliation"], {"api_id": api, "image_id": IMAGE, "running": True})
        self.assertEqual(state["last_success"], prior)
        self.assertEqual(read_override(self.root), IMAGE)
        self.assertEqual(read_only(operation), ExitCode.PREFLIGHT_REFUSED)
        self.assertEqual(read_only(target), ExitCode.OK)
        self.assertEqual(deploy(self.request, self.root), ExitCode.OK)
        self.assertEqual(history(self.root)[operation], closed)
        self.run.assert_not_called()

    def test_wrong_id_and_already_closed_operation_are_refused(self):
        operation = self.pending()
        self.assertEqual(reconcile("f" * 32, close=True), ExitCode.STATE_UNCERTAIN)
        self.assertEqual(read_state(self.root)["latest"]["status"], "pending")
        self.assertEqual(reconcile(operation, close=True), ExitCode.OK)
        closed = read_state(self.root)
        self.assertEqual(reconcile(operation, close=True), ExitCode.STATE_UNCERTAIN)
        self.assertEqual(read_state(self.root), closed)

    def test_foreign_checkout_is_refused_even_with_pending_override(self):
        operation = self.pending(override=OTHER)
        self.api["Config"]["Labels"][LABEL + "project.working_dir"] = "/another-checkout"
        self.assertEqual(reconcile(operation, close=True), ExitCode.STATE_UNCERTAIN)
        self.assertEqual(read_override(self.root), OTHER)
        self.assertEqual(read_state(self.root)["latest"]["status"], "pending")

    def test_verify_only_pending_cannot_repair_a_mismatch(self):
        operation = self.pending(override=OTHER, action="verify-only")
        self.assertEqual(reconcile(operation, close=True), ExitCode.STATE_UNCERTAIN)
        self.assertEqual(read_override(self.root), OTHER)

    def test_legacy_pending_without_a_recorded_replacement_cannot_repair_a_mismatch(self):
        operation = self.pending(override=OTHER, action=None)
        self.assertEqual(reconcile(operation, close=True), ExitCode.STATE_UNCERTAIN)
        self.assertEqual(read_state(self.root)["latest"]["status"], "pending")
        self.assertEqual(read_override(self.root), OTHER)

    def test_unrelated_override_mismatch_is_refused(self):
        unexpected = "sha256:" + "c" * 64
        operation = self.pending(override=unexpected)
        self.assertEqual(reconcile(operation, close=True), ExitCode.STATE_UNCERTAIN)
        self.assertEqual(read_override(self.root), unexpected)

    def test_corrupt_state_and_conflicting_archive_cannot_be_closed(self):
        operation = self.pending()
        state_path = self.directory / "state.json"
        original = state_path.read_bytes()
        state_path.write_text("{ invalid")
        self.assertEqual(reconcile(operation, close=True), ExitCode.STATE_UNCERTAIN)
        self.assertEqual(state_path.read_text(), "{ invalid")
        state_path.write_bytes(original)
        # Completed archive with the same ID conflicts with a pending snapshot.
        archive = dict(read_state(self.root)["latest"], status="failed",
                       finished_at="2026-01-01T00:00:00+00:00")
        archive["checks"] = dict.fromkeys(("container", "liveness", "identity", "catalogue", "proxy"), False)
        (self.directory / f"operation-{operation}.json").write_text(json.dumps(archive))
        self.assertEqual(reconcile(operation, close=True), ExitCode.STATE_UNCERTAIN)
        self.assertEqual(state_path.read_bytes(), original)

    def test_preview_can_read_pending_while_confirmation_obeys_lock(self):
        operation = self.pending()
        with operation_session(self.root, allow_pending=True):
            self.assertEqual(reconcile(operation), ExitCode.OK)
            self.assertEqual(reconcile(operation, close=True), ExitCode.LOCKED)
        self.assertEqual(read_state(self.root)["latest"]["status"], "pending")

    def test_resource_change_between_samples_blocks_closure(self):
        operation = self.pending(override=OTHER)
        first = observe_pending(self.root, self.docker, read_state(self.root)["latest"])
        other = dict(first[0], api_id="f" * 64)
        with patch("toolkit.reconcile.observe_pending", side_effect=[first, (other, OTHER, True)]):
            self.assertEqual(reconcile(operation, close=True), ExitCode.STATE_UNCERTAIN)
        self.assertEqual(read_override(self.root), OTHER)

    def test_retry_after_override_alignment_and_failed_record_preserves_outcome(self):
        operation = self.pending(override=OTHER)
        with patch.object(OperationJournal, "close_unknown", side_effect=RecordError):
            self.assertEqual(reconcile(operation, close=True), ExitCode.RECORD_FAILED)
        self.assertEqual(read_override(self.root), IMAGE)
        self.assertEqual(read_state(self.root)["latest"]["status"], "pending")
        self.assertEqual(reconcile(operation, close=True), ExitCode.OK)
        self.assertEqual(read_state(self.root)["latest"]["status"], CLOSED_UNKNOWN)

    def test_legacy_pending_without_marker_can_be_closed_and_archived(self):
        operation = self.pending(action=None)
        marker = self.directory / "initialized.json"
        marker.unlink()
        self.assertEqual(reconcile(operation, close=True), ExitCode.OK)
        self.assertTrue(marker.is_file())
        state = read_state(self.root)
        self.assertEqual(state["version"], 4)
        self.assertEqual(state["latest"]["status"], CLOSED_UNKNOWN)
        self.assertIsNone(state["last_success"])
        self.assertEqual(deploy(self.request, self.root), ExitCode.OK)
        self.assertEqual(history(self.root)[operation], state["latest"])
