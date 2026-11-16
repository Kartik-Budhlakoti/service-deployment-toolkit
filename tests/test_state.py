from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from toolkit.cli import main
from toolkit.locking import LockBusy
from toolkit.state import RecordError, StateUncertain, operation_session, read_state, state_directory


IMAGE = "sha256:" + "a" * 64
NEXT_IMAGE = "sha256:" + "b" * 64


class OperationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.directory = state_directory(self.root)

    def run_child(self, code):
        return subprocess.run(
            [sys.executable, "-c", code, str(self.root)],
            capture_output=True, text=True, timeout=10,
        )

    def test_fresh_read_creates_no_state(self):
        self.assertIsNone(read_state(self.root)["latest"])
        self.assertFalse(self.directory.parent.exists())

    def test_another_process_cannot_take_the_lock(self):
        with operation_session(self.root):
            result = self.run_child(
                "import sys\n"
                "from toolkit.locking import LockBusy\n"
                "from toolkit.state import operation_session\n"
                "try:\n"
                "    with operation_session(sys.argv[1]):\n"
                "        sys.exit(2)\n"
                "except LockBusy:\n"
                "    sys.exit(5)\n"
            )
        self.assertEqual(result.returncode, 5, result.stderr)
        with operation_session(self.root):
            pass

    def test_abrupt_exit_leaves_pending_and_releases_lock(self):
        result = self.run_child(
            "import sys, os\n"
            "from toolkit.state import operation_session\n"
            "with operation_session(sys.argv[1]) as journal:\n"
            f"    journal.begin({IMAGE!r}, 'demo-v1')\n"
            "    os._exit(19)\n"
        )
        self.assertEqual(result.returncode, 19, result.stderr)
        self.assertEqual(read_state(self.root)["latest"]["status"], "pending")
        with self.assertRaises(StateUncertain), operation_session(self.root):
            self.fail("An unfinished operation must block the session")

    def test_failure_preserves_last_success_and_archives_previous_record(self):
        with operation_session(self.root) as journal:
            first = journal.begin(IMAGE, "demo-v1")
            journal.finish(first, "succeeded")
        with operation_session(self.root) as journal:
            second = journal.begin(NEXT_IMAGE, "demo-v2")
            journal.finish(second, "failed")
        state = read_state(self.root)
        self.assertEqual(state["latest"]["status"], "failed")
        self.assertEqual(state["last_success"]["image_id"], IMAGE)
        previous = json.loads((self.directory / f"operation-{first}.json").read_text())
        self.assertEqual(previous, state["last_success"])

    def test_first_failure_does_not_create_recovery_target(self):
        with operation_session(self.root) as journal:
            operation = journal.begin(IMAGE, "demo-v1")
            journal.finish(operation, "failed")
        self.assertIsNone(read_state(self.root)["last_success"])

    def test_wrong_operation_id_leaves_pending(self):
        with operation_session(self.root) as journal:
            operation = journal.begin(IMAGE, "demo-v1")
            with self.assertRaises(StateUncertain):
                journal.finish("wrong", "succeeded")
            self.assertEqual(read_state(self.root)["latest"]["id"], operation)
            self.assertEqual(read_state(self.root)["latest"]["status"], "pending")

    def test_invalid_file_refuses_mutation_and_remains_intact(self):
        self.directory.mkdir(parents=True)
        state = self.directory / "state.json"
        for data in (b"{", b'{"version": 2, "latest": null, "last_success": null}', b"x" * 8193):
            with self.subTest(size=len(data)):
                state.write_bytes(data)
                with self.assertRaises(StateUncertain), operation_session(self.root):
                    self.fail("Invalid state must block the session")
                self.assertEqual(state.read_bytes(), data)

    def test_missing_snapshot_with_archive_is_uncertain(self):
        self.directory.mkdir(parents=True)
        (self.directory / "operation-old.json").touch()
        with self.assertRaises(StateUncertain):
            read_state(self.root)

    def test_failed_atomic_replace_preserves_previous_snapshot(self):
        with operation_session(self.root) as journal:
            operation = journal.begin(IMAGE, "demo-v1")
            previous = (self.directory / "state.json").read_bytes()
            with patch("toolkit.state.os.replace", side_effect=OSError):
                with self.assertRaises(RecordError):
                    journal.finish(operation, "succeeded")
            self.assertEqual((self.directory / "state.json").read_bytes(), previous)
            self.assertEqual(list(self.directory.glob(".write-*")), [])
            with self.assertRaises(RuntimeError):
                journal.finish(operation, "succeeded")

    def test_failed_initial_record_does_not_return_operation_id(self):
        with operation_session(self.root) as journal:
            with patch("toolkit.state.os.replace", side_effect=OSError):
                with self.assertRaises(RecordError):
                    journal.begin(IMAGE, "demo-v1")
        self.assertIsNone(read_state(self.root)["latest"])

    def test_state_symlink_refused(self):
        self.directory.mkdir(parents=True)
        external = self.root / "external.json"
        external.write_text("untouched")
        (self.directory / "state.json").symlink_to(external)
        with self.assertRaises(StateUncertain):
            read_state(self.root)
        self.assertEqual(external.read_text(), "untouched")

    def test_status_remains_available_with_unfinished_state(self):
        with operation_session(self.root) as journal:
            journal.begin(IMAGE, "demo-v1")
        stdout, stderr = io.StringIO(), io.StringIO()
        rows = [{"service": "api", "state": "running", "image_id": IMAGE}]
        with patch("toolkit.state.Path.cwd", return_value=self.root), patch(
                "toolkit.cli.inspect_status", return_value=rows
        ), redirect_stdout(stdout), redirect_stderr(stderr):
            self.assertEqual(main(["status"]), 6)
        self.assertIn("pending", stdout.getvalue())
        self.assertIn("api: running", stdout.getvalue())
        self.assertIn("STATE UNCERTAIN", stderr.getvalue())

    def test_session_cannot_write_after_unlock(self):
        with operation_session(self.root) as journal:
            pass
        with self.assertRaises(RuntimeError):
            journal.begin(IMAGE, "demo-v1")
