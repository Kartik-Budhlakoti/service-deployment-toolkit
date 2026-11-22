from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from uuid import uuid4

from .config import ConfigurationError, Settings, validate_release
from .locking import mutation_lock
from .docker import unique_object


MAX_RECORD_BYTES = 8192
EMPTY = {"version": 1, "latest": None, "last_success": None}
MARKER = {"version": 1, "purpose": "operation-journal"}


class StateUncertain(RuntimeError):
    pass


class RecordError(RuntimeError):
    pass


def state_directory(root=None):
    return Path(root or Path.cwd()).resolve() / Settings().state_directory


def _check_directory(path, create=False):
    for directory in (path.parent, path):
        if create:
            directory.mkdir(mode=0o700, exist_ok=True)
        try:
            mode = directory.lstat().st_mode
        except FileNotFoundError:
            return
        if not stat.S_ISDIR(mode):
            raise OSError("Expected a real state directory")


def _matches(pattern, value):
    return isinstance(value, str) and re.fullmatch(pattern, value) is not None


CHECK_NAMES = ("container", "liveness", "identity", "catalogue", "proxy")
CLOSED_UNKNOWN = "closed-unknown"


def _check_reconciliation(observation):
    if (type(observation) is not dict or set(observation) != {"api_id", "image_id", "running"}
            or not _matches(r"[0-9a-f]{64}", observation["api_id"])
            or not _matches(r"sha256:[0-9a-f]{64}", observation["image_id"])
            or type(observation["running"]) is not bool):
        raise ValueError("Invalid reconciliation observation")


def _record_version(record):
    if ("reconciliation" in record or "auto_target" in record
            or record.get("recovery", {}).get("kind") == "automatic"):
        return 4
    if "recovery" in record:
        return 3
    return 2 if "action" in record else 1


def _check_record(record):
    required = {"id", "status", "image_id", "release", "started_at", "finished_at"}
    extended = required | {"action", "checks"}
    shapes = (required, extended, extended | {"recovery", "evidence"},
              extended | {"auto_target", "evidence"})
    if type(record) is not dict or (set(record) - {"reconciliation"}) not in shapes:
        raise ValueError
    status = record["status"]
    if ("reconciliation" in record) != (status == CLOSED_UNKNOWN):
        raise ValueError
    if "reconciliation" in record:
        _check_reconciliation(record["reconciliation"])
    if "recovery" in record:
        meta = record["recovery"]
        if type(meta) is not dict:
            raise ValueError
        fields = {"kind", "target", "requested", "needed"}
        if meta.get("kind") == "automatic":
            fields.add("trigger")
        if set(meta) != fields:
            raise ValueError
        if type(meta["requested"]) is not bool or type(meta["needed"]) is not bool:
            raise ValueError
        if meta["needed"] and not meta["requested"]:
            raise ValueError
        if meta["kind"] == "baseline":
            if meta["target"] is not None or meta["requested"] or meta["needed"]:
                raise ValueError
        elif (meta["kind"] not in ("rollback", "automatic") or meta["target"] == record["id"]
              or not _matches(r"[0-9a-f]{32}", meta["target"])):
            raise ValueError
        if meta["kind"] == "automatic" and (
            meta["requested"] or record["action"] != "replace"
            or not _matches(r"[0-9a-f]{32}", meta["trigger"])
            or meta["trigger"] in (meta["target"], record["id"])
        ):
            raise ValueError
    if "auto_target" in record and (
        not _matches(r"[0-9a-f]{32}", record["auto_target"])
        or record["auto_target"] == record["id"] or record["action"] != "replace"
    ):
        raise ValueError
    if "evidence" in record:
        if (record["evidence"] is not None) != (status == "succeeded"):
            raise ValueError
        if record["evidence"] is not None and type(record["evidence"]) is not dict:
            raise ValueError
    if "action" in record:
        if record["action"] not in ("verify-only", "replace"):
            raise ValueError
        if status in ("pending", CLOSED_UNKNOWN):
            if record["checks"] is not None:
                raise ValueError
        else:
            _check_results(record["checks"])
            if record["status"] == "succeeded" and not all(record["checks"].values()):
                raise ValueError
    if not _matches(r"[0-9a-f]{32}", record["id"]):
        raise ValueError
    if not _matches(r"sha256:[0-9a-f]{64}", record["image_id"]):
        raise ValueError
    validate_release(record["release"])
    started = datetime.fromisoformat(record["started_at"])
    if started.utcoffset() != timezone.utc.utcoffset(None):
        raise ValueError
    if status == "pending" and record["finished_at"] is None:
        return
    if status not in ("succeeded", "failed", CLOSED_UNKNOWN):
        raise ValueError
    finished = datetime.fromisoformat(record["finished_at"])
    if finished.utcoffset() != timezone.utc.utcoffset(None):
        raise ValueError


def _check_results(checks):
    if (type(checks) is not dict or set(checks) != set(CHECK_NAMES)
            or any(type(value) is not bool for value in checks.values())):
        raise ValueError("Expected five boolean check results")


def _read_json(path):
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    with os.fdopen(os.open(path, flags), "rb") as file:
        if not stat.S_ISREG(os.fstat(file.fileno()).st_mode):
            raise ValueError
        data = file.read(MAX_RECORD_BYTES + 1)
    if len(data) > MAX_RECORD_BYTES:
        raise ValueError
    return json.loads(data, object_pairs_hook=unique_object)


def read_state(root=None):
    directory = state_directory(root)
    try:
        _check_directory(directory)
        initialized = _read_marker(directory)
        try:
            state = _read_json(directory / "state.json")
        except FileNotFoundError:
            if initialized or any(directory.glob("operation-*.json")):
                raise ValueError
            return EMPTY.copy()
        if type(state) is not dict or state.keys() != EMPTY.keys():
            raise ValueError
        if type(state["version"]) is not int or state["version"] not in (1, 2, 3, 4):
            raise ValueError
        latest = state["latest"]
        last_success = state["last_success"]
        _check_record(latest)
        if state["version"] >= 2 and not initialized:
            raise ValueError
        if state["version"] == 1:
            # Older readers allowed a completed action record in a v1 snapshot.
            if _record_version(latest) > 2:
                raise ValueError
        elif state["version"] != _record_version(latest):
            raise ValueError
        if last_success is not None:
            _check_record(last_success)
            if last_success["status"] != "succeeded":
                raise ValueError
        if latest["status"] == "succeeded":
            if latest != last_success:
                raise ValueError
        elif last_success is not None and latest["id"] == last_success["id"]:
            raise ValueError
        return state
    except (OSError, ValueError, TypeError, RecursionError):
        raise StateUncertain("Operation state is unreadable, invalid or unsupported") from None


def _read_marker(directory):
    try:
        marker = _read_json(directory / "initialized.json")
    except FileNotFoundError:
        return False
    if (type(marker) is not dict or marker != MARKER
            or type(marker.get("version")) is not int):
        raise ValueError("Invalid journal marker")
    return True


def _sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_json(path, value):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False, mode="w",
                                         encoding="utf-8", prefix=".write-") as file:
            temporary = Path(file.name)
            json.dump(value, file, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
        temporary = None
        _sync_directory(path.parent)
    except OSError:
        raise RecordError("Could not save the operation record") from None
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


class OperationJournal:
    def __init__(self, directory, state):
        self._directory = directory
        self._state = state
        self._closed = False

    @property
    def latest(self):
        return self._state["latest"]

    @property
    def last_success(self):
        return self._state["last_success"]

    def begin(self, image_id, release, action=None, recovery=None, auto_target=None):
        if self._closed:
            raise RuntimeError("Operation session is closed")
        if not _matches(r"sha256:[0-9a-f]{64}", image_id):
            raise ConfigurationError("Recording requires a full SHA-256 image ID")
        validate_release(release)
        if action is not None and action not in ("verify-only", "replace"):
            raise ValueError("Unknown operation action")
        latest = self._state["latest"]
        if latest is not None and latest["status"] == "pending":
            raise StateUncertain("An unfinished operation requires inspection")
        record = {
            "id": uuid4().hex,
            "status": "pending",
            "image_id": image_id,
            "release": release,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
        }
        if action is not None:
            record.update(action=action, checks=None)
        if recovery is not None:
            record.update(recovery=dict(recovery), evidence=None)
        if auto_target is not None:
            record.update(auto_target=auto_target, evidence=None)
        _check_record(record)
        if auto_target is not None and (
            self.last_success is None or auto_target != self.last_success["id"]
            or self.last_success.get("evidence") is None
        ):
            raise StateUncertain("The automatic recovery baseline is no longer the last recorded success")
        if recovery and recovery["kind"] == "automatic" and (
            latest is None or latest["status"] != "failed" or latest["id"] != recovery["trigger"]
            or latest.get("auto_target") != recovery["target"]
            or self.last_success is None or self.last_success["id"] != recovery["target"]
        ):
            raise StateUncertain("Automatic recovery requires the immediately preceding recorded failure")
        try:
            # Save the marker first: interruption here must not look like first use.
            if not _read_marker(self._directory):
                _write_json(self._directory / "initialized.json", MARKER)
            if latest is not None:
                _write_json(self._directory / f"operation-{latest['id']}.json", latest)
            self._save(record, self._state["last_success"])
        except (OSError, ValueError, RecursionError) as error:
            self._closed = True
            raise StateUncertain("Journal marker became unreadable or invalid") from error
        except RecordError:
            self._closed = True
            raise
        return record["id"]

    def _pending(self, operation_id):
        if self._closed:
            raise RuntimeError("Operation session is closed")
        latest = self.latest
        if latest is None or latest["id"] != operation_id or latest["status"] != "pending":
            raise StateUncertain("The requested operation is not the pending operation")
        return latest

    def finish(self, operation_id, outcome, checks=None, evidence=None):
        latest = self._pending(operation_id)
        if outcome not in ("succeeded", "failed"):
            raise ValueError("Finish requires a known success or failure")
        record = dict(latest, status=outcome, finished_at=datetime.now(timezone.utc).isoformat())
        if "action" in record:
            _check_results(checks)
            if outcome == "succeeded" and not all(checks.values()):
                raise ValueError("Success requires all checks to pass")
            record["checks"] = dict(checks)
        elif checks is not None:
            raise ValueError("Legacy records do not support check results")
        if "evidence" in record:
            record["evidence"] = evidence
            _check_record(record)
        last_success = record if outcome == "succeeded" else self._state["last_success"]
        self._save(record, last_success)

    def close_unknown(self, operation_id, observation):
        latest = self._pending(operation_id)
        record = dict(latest, status=CLOSED_UNKNOWN, reconciliation=dict(observation),
                      finished_at=datetime.now(timezone.utc).isoformat())
        _check_record(record)
        try:
            if not _read_marker(self._directory):
                _write_json(self._directory / "initialized.json", MARKER)
        except (OSError, ValueError, RecursionError):
            raise StateUncertain("Journal marker became unreadable or invalid") from None
        self._save(record, self.last_success)

    def _save(self, record, last_success):
        state = {"version": _record_version(record), "latest": record, "last_success": last_success}
        try:
            _write_json(self._directory / "state.json", state)
        except RecordError:
            self._closed = True
            raise
        self._state = state


@contextmanager
def operation_session(root=None, *, allow_pending=False):
    root = Path(root or Path.cwd()).resolve()
    directory = state_directory(root)
    with ExitStack() as stack:
        try:
            _check_directory(directory, create=True)
            stack.enter_context(mutation_lock(directory / "mutation.lock"))
            _sync_directory(directory.parent)
            _sync_directory(directory.parent.parent)
        except OSError:
            raise RecordError("Could not prepare the operation directory or lock") from None
        state = read_state(root)
        if not allow_pending and state["latest"] is not None and state["latest"]["status"] == "pending":
            raise StateUncertain("An unfinished operation requires inspection")
        journal = OperationJournal(directory, state)
        try:
            yield journal
        finally:
            journal._closed = True
