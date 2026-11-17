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


def _check_record(record):
    if type(record) is not dict or set(record) != {
        "id", "status", "image_id", "release", "started_at", "finished_at"
    }:
        raise ValueError
    if not _matches(r"[0-9a-f]{32}", record["id"]):
        raise ValueError
    if not _matches(r"sha256:[0-9a-f]{64}", record["image_id"]):
        raise ValueError
    validate_release(record["release"])
    started = datetime.fromisoformat(record["started_at"])
    if started.utcoffset() != timezone.utc.utcoffset(None):
        raise ValueError
    status = record["status"]
    if status == "pending" and record["finished_at"] is None:
        return
    if status not in ("succeeded", "failed"):
        raise ValueError
    finished = datetime.fromisoformat(record["finished_at"])
    if finished.utcoffset() != timezone.utc.utcoffset(None):
        raise ValueError


def _read_json(path):
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    with os.fdopen(os.open(path, flags), "rb") as file:
        if not stat.S_ISREG(os.fstat(file.fileno()).st_mode):
            raise ValueError
        data = file.read(MAX_RECORD_BYTES + 1)
    if len(data) > MAX_RECORD_BYTES:
        raise ValueError
    return json.loads(data)


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
        if type(state["version"]) is not int or state["version"] != 1:
            raise ValueError
        latest = state["latest"]
        last_success = state["last_success"]
        _check_record(latest)
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

    def begin(self, image_id, release):
        if self._closed:
            raise RuntimeError("Operation session is closed")
        if not _matches(r"sha256:[0-9a-f]{64}", image_id):
            raise ConfigurationError("Recording requires a full SHA-256 image ID")
        validate_release(release)
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

    def finish(self, operation_id, outcome):
        if self._closed:
            raise RuntimeError("Operation session is closed")
        latest = self._state["latest"]
        if latest is None or latest["id"] != operation_id or latest["status"] != "pending":
            raise StateUncertain("The requested operation is not the pending operation")
        if outcome not in ("succeeded", "failed"):
            raise ValueError("Finish requires a known success or failure")
        record = dict(latest, status=outcome, finished_at=datetime.now(timezone.utc).isoformat())
        last_success = record if outcome == "succeeded" else self._state["last_success"]
        self._save(record, last_success)

    def _save(self, record, last_success):
        state = {"version": 1, "latest": record, "last_success": last_success}
        try:
            _write_json(self._directory / "state.json", state)
        except RecordError:
            self._closed = True
            raise
        self._state = state


@contextmanager
def operation_session(root=None):
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
        if state["latest"] is not None and state["latest"]["status"] == "pending":
            raise StateUncertain("An unfinished operation requires inspection")
        journal = OperationJournal(directory, state)
        try:
            yield journal
        finally:
            journal._closed = True
