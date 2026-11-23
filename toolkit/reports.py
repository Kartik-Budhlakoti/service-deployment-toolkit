"""Local incident reports derived from the operation journal."""
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import stat
import sys

from .config import ExitCode
from .locking import LockBusy
from .recovery import history
from .state import RecordError, StateUncertain, _sync_directory, _write_json, operation_session, read_state


def summary(record):
    def timestamp(name):
        value = record[name]
        return datetime.fromisoformat(value).isoformat() if value else None

    return {
        "id": record["id"],
        "outcome": record["status"],
        "action": record.get("action"),
        "image_id": record["image_id"],
        "started_at": timestamp("started_at"),
        "finished_at": timestamp("finished_at"),
        "checks": record.get("checks"),
        "verification": record.get("verification_trace"),
        "reconciliation": record.get("reconciliation"),
        "recovery_request": record.get("recovery"),
        "automatic_target": record.get("auto_target"),
    }


def save_report(root, records, selected):
    record = records[selected]
    operation = records[record.get("recovery", {}).get("trigger", selected)]
    recovery = next((r for r in records.values()
                     if r.get("recovery", {}).get("trigger") == operation["id"]), None)
    report = {"version": 1, "operation": summary(operation),
              "automatic_recovery": summary(recovery) if recovery else None}

    directory = root / "reports"
    directory.mkdir(mode=0o700, exist_ok=True)
    if not stat.S_ISDIR(directory.lstat().st_mode):
        raise OSError("Expected a local reports directory")
    _sync_directory(root)
    path = directory / f"operation-{operation['id']}.json"
    _write_json(path, report)
    print(f"REPORT: reports/{path.name}")


@contextmanager
def incident_reports(root, journal):
    before = journal.latest
    try:
        yield
    finally:
        latest = journal.latest
        if (latest and latest != before and
                (latest["status"] != "succeeded" or latest.get("recovery", {}).get("trigger"))):
            # Recovery has finished or unwound. No report I/O on its critical path.
            try:
                records = history(root, allow_pending=True)
                if records.get(latest["id"]) != latest:
                    raise StateUncertain("Latest operation changed")
                save_report(root, records, latest["id"])
            except (RecordError, StateUncertain, OSError):
                print("REPORT UNAVAILABLE: inspect the journal before regenerating the report.", file=sys.stderr)


def export_report(operation_id, root=None):
    root = Path(root or Path.cwd()).resolve()
    try:
        if read_state(root)["latest"] is None:
            print("REPORT: no recorded operations.", file=sys.stderr)
            return ExitCode.INVALID_INPUT
        with operation_session(root, allow_pending=True):
            records = history(root, allow_pending=True)
            if operation_id not in records:
                print("REPORT: unknown operation ID.", file=sys.stderr)
                return ExitCode.INVALID_INPUT
            save_report(root, records, operation_id)
        return ExitCode.OK
    except LockBusy:
        print("REPORT BUSY: retry after the current operation.", file=sys.stderr)
        return ExitCode.LOCKED
    except StateUncertain:
        print("REPORT UNAVAILABLE: could not validate the local journal.", file=sys.stderr)
        return ExitCode.STATE_UNCERTAIN
    except (OSError, RecordError):
        print("REPORT UNAVAILABLE: could not save the local report.", file=sys.stderr)
        return ExitCode.RECORD_FAILED
    except KeyboardInterrupt:
        return ExitCode.INTERRUPTED
