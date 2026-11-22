"""Selection from local history and comparison of signed recovery observations."""
import hmac
from pathlib import Path
import re
import sys

from .compatibility import CONTRACT, FIELDS, comparison_key, observe, read_inputs, signed
from .config import DeploymentRequest, ExitCode, Settings
from .docker import Docker, InspectionError
from .preflight import inspect_preflight, require, require_demo_user, validate_replacement_config
from .override import read_override
from .state import StateUncertain, _check_record, _read_json, read_state, state_directory


def history(root):
    state = read_state(root)
    latest = state["latest"]
    if latest and latest["status"] == "pending":
        raise StateUncertain("Pending operation requires inspection")
    records = {}

    def add(record):
        if record:
            if record["id"] in records and record != records[record["id"]]:
                raise StateUncertain("Conflicting records for the same operation")
            records[record["id"]] = record
    add(latest)
    add(state["last_success"])
    directory = state_directory(root)
    try:
        if directory.exists():
            for path in directory.iterdir():
                if not path.name.startswith("operation-"):
                    continue
                if len(records) > 10000:
                    raise StateUncertain("History exceeds the supported limit")
                record = _read_json(path)
                _check_record(record)
                if path.name != f"operation-{record['id']}.json" or record["status"] == "pending":
                    raise ValueError
                add(record)
    except (OSError, ValueError, TypeError, RecursionError):
        raise StateUncertain("Invalid archived operation") from None
    return records


def evidence(key, operation, image, release, snapshot):
    payload = {"version": 1, "contract": CONTRACT, "snapshot": snapshot}
    binding = [operation, image, release, payload]
    return dict(payload, signature=signed(key, "record", binding))


def target_record(records, target):
    record = records.get(target)
    require(record is not None, "Unknown recorded target")
    require(record["status"] == "succeeded", "Target did not succeed")
    require(record.get("evidence") is not None, "Historical success lacks recovery evidence")
    return record


def authenticate(record, key):
    proof = record["evidence"]
    snapshot = proof.get("snapshot")
    require(type(snapshot) is dict and set(snapshot) == FIELDS
            and all(isinstance(v, str) and re.fullmatch("[0-9a-f]{64}", v) for v in snapshot.values())
            and type(proof.get("version")) is int and proof["version"] == 1
            and proof.get("contract") == CONTRACT and set(proof) == {"version", "contract", "snapshot", "signature"},
            "Unsupported or malformed recovery evidence")
    expected = evidence(key, record["id"], record["image_id"], record["release"], snapshot)
    sig = proof["signature"]
    require(isinstance(sig, str) and re.fullmatch("[0-9a-f]{64}", sig)
            and hmac.compare_digest(sig, expected["signature"]), "Record binding or comparison key differs")
    return snapshot


def differences(saved, current, allow):
    changed = {name for name in saved if saved[name] != current[name]}
    if not changed:
        return False
    if changed == {"compose_bytes"} and allow:
        return True
    raise InspectionError("Recovery evidence differs: " + ", ".join(sorted(changed)))


def inspect_target(root, docker, record, allow):
    key = comparison_key(root)
    saved = authenticate(record, key)
    read_inputs(root, docker)
    request = DeploymentRequest(record["image_id"], record["release"], Settings())
    preflight = inspect_preflight(request, root, docker)
    require(preflight["candidate_image_id"] == request.image, "Selected immutable local image is unavailable")
    read_override(root)
    validate_replacement_config(docker, root)
    require_demo_user(docker, request.image)
    snapshot = observe(root, docker, key, request.image)
    return request, key, snapshot, differences(saved, snapshot, allow)


def read_only(target=None, allow=False):
    root = Path.cwd().resolve()
    try:
        records = history(root)
        if target is not None:
            record = target_record(records, target)
            _, _, _, needed = inspect_target(root, Docker(root), record, allow)
            print(f"ELIGIBLE NOW: target={target} release={record['release']} exception_needed={needed}")
            return ExitCode.OK
        successes = sorted((r for r in records.values() if r["status"] == "succeeded"),
                           key=lambda r: (r["finished_at"], r["id"]), reverse=True)
        for record in successes:
            reason = "strictly eligible now"
            try:
                target_record(records, record["id"])
                inspect_target(root, Docker(root), record, False)
            except InspectionError as error:
                reason = str(error)
            print(record["id"], record["release"], record["image_id"][:19], record["finished_at"], reason)
        if not successes:
            print("No recorded successes.")
        return ExitCode.OK
    except InspectionError as error:
        print(f"RECOVERY REFUSED: {error}", file=sys.stderr)
        return ExitCode.PREFLIGHT_REFUSED
    except StateUncertain as error:
        print(f"STATE UNCERTAIN: {error}", file=sys.stderr)
        return ExitCode.STATE_UNCERTAIN
