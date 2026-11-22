"""Run the remaining Phase 3 exercises on the dedicated demo."""
import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from toolkit.config import DeploymentRequest, ExitCode, Settings
from toolkit.docker import Docker, InspectionError
from toolkit.override import override_path, read_override
from toolkit.preflight import LABEL, inspect_preflight, single
from toolkit.recovery import history
from toolkit.state import CLOSED_UNKNOWN, StateUncertain, read_state, state_directory

RELEASE = "demo-v1"
FAILURE_RELEASE = "phase3-startup-failure"
VERIFICATION_SECONDS = "15"
ABRUPT_EXIT = 87
STARTUP_EXIT = 42


def check(condition, message):
    if not condition:
        raise AcceptanceError(message)


class AcceptanceError(RuntimeError):
    pass


def run(args, expected=0, required_output=None):
    result = subprocess.run(args, cwd=ROOT, text=True, capture_output=required_output is not None)
    if required_output is not None:
        print(result.stdout, end="", flush=True)
        print(result.stderr, end="", file=sys.stderr, flush=True)
    check(result.returncode == expected,
          f"Expected exit {expected}, observed {result.returncode} from {Path(args[0]).name}")
    if required_output is not None:
        check(required_output in result.stdout + result.stderr,
              f"Expected the command to report {required_output}")


def cli(*args, expected=0, required_output=None):
    run([sys.executable, "-m", "toolkit", *args], expected, required_output)


def inspect(image, release=RELEASE):
    return inspect_preflight(DeploymentRequest(image, release, Settings()), ROOT)


def running_v1():
    state = read_state(ROOT)
    check(not state["latest"] or state["latest"]["status"] != "pending",
          "The demo already has a pending operation. Inspect toolkit status first")
    before = inspect("sdt-demo-api:phase1")
    check(before["api_running"] and before["current_image_id"] == before["candidate_image_id"],
          "Start the exercise with the existing Phase 1 image running as demo-v1")
    run([sys.executable, "tests/smoke.py"])
    return before


def build_failing_candidate():
    tag = "sdt-demo-api:phase3-startup-failure-" + uuid4().hex[:12]
    with tempfile.TemporaryDirectory(prefix="sdt-phase3-build-") as temporary:
        context = Path(temporary) / "demo"
        for name in ("requirements.lock", "app/__init__.py", "app/main.py", "app/release.txt", "db/initialize.py"):
            target = context / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / "demo" / name, target)
        template = (ROOT / "demo/Dockerfile").read_text().rstrip()
        body, marker, original_cmd = template.rpartition("\nCMD ")
        check(marker and "\n" not in original_cmd, "Expected the demo Dockerfile's final CMD instruction")
        # Docker starts this process successfully. It exits before serving HTTP.
        command = ["python", "-c", f"import time; time.sleep(4); raise SystemExit({STARTUP_EXIT})"]
        (context / "Dockerfile").write_text(body + marker + json.dumps(command) + "\n")
        run(["docker", "--context", "default", "build", "--pull=false", "-t", tag, str(context)])
    return inspect(tag, FAILURE_RELEASE)["candidate_image_id"]


def deploy_candidate(image, *, automatic=False, expected=ExitCode.DEPLOYMENT_FAILED,
                     required_output=None):
    arguments = ["deploy", "--image", image, "--release", FAILURE_RELEASE,
                 "--verification-timeout", VERIFICATION_SECONDS]
    if automatic:
        arguments.extend(("--auto-recover", "--schema", "catalogue-v1"))
    cli(*arguments, expected=expected, required_output=required_output)


def register(image):
    cli("baseline", "--image", image, "--release", RELEASE, "--schema", "catalogue-v1")
    return read_state(ROOT)["last_success"]["id"]


def confirm_restored(original, image):
    live = inspect(image)
    check(live["api_running"] and live["current_image_id"] == image
          and live["dependency_ids"] == original["dependency_ids"],
          "The recorded v1 or dependency identities differ after recovery")
    run([sys.executable, "tests/smoke.py"])
    return live


def interrupt_replacement(candidate, *, after):
    child = """
import importlib
import os
import sys
from unittest.mock import patch

from toolkit.cli import main

module = importlib.import_module("toolkit.deploy")
replace = module.run_command
when, exit_code, *args = sys.argv[1:]

def interrupt(*args, **kwargs):
    if when == "after":
        replace(*args, **kwargs)
    os._exit(int(exit_code))

with patch.object(module, "run_command", interrupt):
    sys.exit(main(args))
"""
    run([sys.executable, "-u", "-c", child, "after" if after else "before", str(ABRUPT_EXIT),
         "deploy", "--image", candidate, "--release", FAILURE_RELEASE], expected=ABRUPT_EXIT)
    pending = read_state(ROOT)["latest"]
    check(pending["status"] == "pending" and pending["image_id"] == candidate
          and read_override(ROOT) == candidate, "The interruption fixture did not retain intent and the override")
    return pending["id"]


def settle_interruption(operation, candidate, saved_success):
    state_path = state_directory(ROOT) / "state.json"
    raw = state_path.read_bytes()
    cli("deploy", "--image", saved_success["image_id"], "--release", RELEASE,
        expected=ExitCode.STATE_UNCERTAIN, required_output="unfinished operation")
    cli("reconcile", "--operation", operation)
    check(state_path.read_bytes() == raw and read_override(ROOT) == candidate,
          "Preview or a refused command changed the pending files")
    cli("reconcile", "--operation", operation, "--close-unknown")
    result = read_state(ROOT)
    check(result["latest"]["id"] == operation and result["latest"]["status"] == CLOSED_UNKNOWN
          and result["last_success"] == saved_success, "Reconciliation changed the recorded outcome or previous success")


def exited_candidate(candidate, before):
    deadline = time.monotonic() + 15
    while True:
        observed = inspect(candidate, FAILURE_RELEASE)
        check(observed["current_image_id"] == candidate and observed["api_id"] != before["api_id"]
              and observed["dependency_ids"] == before["dependency_ids"], "Expected the test candidate and prior dependencies")
        api = single(Docker(ROOT).json("container", "inspect", observed["api_id"]), "test API container")
        if api["State"]["Status"] == "exited":
            check(api["State"]["ExitCode"] == STARTUP_EXIT and api["State"]["OOMKilled"] is False,
                  "The candidate exited for a different reason than the test")
            return observed
        check(time.monotonic() < deadline, "Candidate process did not exit within 15 seconds")
        time.sleep(0.25)


def exercise_reconciliation(before, candidate):
    original_image = before["current_image_id"]
    register(original_image)
    saved_success = read_state(ROOT)["last_success"]
    api = single(Docker(ROOT).json("container", "inspect", before["api_id"]), "API container")
    files = api["Config"]["Labels"][LABEL + "project.config_files"]
    toolkit_owned = files == f"{ROOT / 'compose.yaml'},{override_path(ROOT)}"
    operation = interrupt_replacement(candidate, after=False)
    settle_interruption(operation, candidate, saved_success)
    if toolkit_owned:
        check(read_override(ROOT) == original_image, "Reconciliation left the toolkit-owned API and override out of sync")
    after = confirm_restored(before, original_image)
    check(after["api_id"] == before["api_id"], "The reconciliation exercise replaced the API")
    print("PASS: interruption before replacement preserved the original API", flush=True)

    operation = interrupt_replacement(candidate, after=True)
    replaced = exited_candidate(candidate, before)
    settle_interruption(operation, candidate, saved_success)
    current = inspect(candidate, FAILURE_RELEASE)
    check(current == replaced and read_override(ROOT) == candidate,
          "Closure changed the API or the matching override")
    cli("rollback", "--to", saved_success["id"])
    restored = confirm_restored(before, original_image)
    check(restored["api_id"] != replaced["api_id"], "Manual recovery did not replace the exited API")
    print("PASS: interruption after replacement retained the failed API until explicit manual rollback", flush=True)
    return restored


@contextmanager
def temporary_comment():
    path = ROOT / "compose.yaml"
    original = path.read_bytes()
    extra = b"\n# Temporary Phase 3 strict recovery acceptance comment\n"
    with path.open("r+b") as stream:
        check(stream.read() == original, "Compose file changed before the comment exercise")
        stream.write(extra)
    try:
        yield
    finally:
        with path.open("r+b") as stream:
            check(stream.read() == original + extra, "Unexpected concurrent Compose edit. Inspect the file before retrying")
            stream.truncate(len(original))


def exercise_automatic_recovery(before, candidate):
    original_image = before["current_image_id"]
    target = register(original_image)
    saved = read_state(ROOT)
    with temporary_comment():
        deploy_candidate(candidate, automatic=True, expected=ExitCode.PREFLIGHT_REFUSED,
                         required_output="Recovery evidence differs: compose_bytes")
        check(read_state(ROOT) == saved and inspect(original_image) == before,
              "The strict preflight refusal changed the journal or resources")
    print("PASS: opt-in preflight refused a comment-only change", flush=True)

    deploy_candidate(candidate)
    failed = read_state(ROOT)
    live = exited_candidate(candidate, before)
    check(failed["latest"]["status"] == "failed" and failed["last_success"]["id"] == target
          and live["current_image_id"] == candidate and not live["api_running"]
          and live["api_id"] != before["api_id"] and live["dependency_ids"] == before["dependency_ids"],
          "The failed default deployment did not leave the expected stopped candidate")
    cli("rollback", "--to", target)
    restored = confirm_restored(before, original_image)
    check(restored["api_id"] != live["api_id"] and restored["api_id"] != before["api_id"],
          "Strict manual recovery did not create a new API container")
    print("PASS: default deploy left the failed candidate, and strict manual rollback restored v1", flush=True)

    previous = read_state(ROOT)["last_success"]
    deploy_candidate(candidate, automatic=True)
    state = read_state(ROOT)
    recovery = state["latest"]
    metadata = recovery.get("recovery", {})
    check(recovery["status"] == "succeeded" and recovery["image_id"] == original_image
          and state["last_success"] == recovery and metadata.get("kind") == "automatic"
          and metadata["target"] == previous["id"] and metadata["requested"] is False
          and metadata["needed"] is False, "Automatic recovery result was not recorded as expected")
    operations = history(ROOT)
    trigger = operations[metadata["trigger"]]
    check(trigger["status"] == "failed" and trigger["image_id"] == candidate
          and trigger["auto_target"] == previous["id"], "The failed deployment record was not preserved")
    attempts = [entry for entry in operations.values()
                if entry.get("recovery", {}).get("trigger") == trigger["id"]]
    check(len(attempts) == 1, "Expected exactly one recovery attempt")
    final = confirm_restored(before, original_image)
    check(final["api_id"] != restored["api_id"], "Automatic recovery did not replace the API")
    print("PASS: automatic recovery restored v1 once and the deploy command still exited 1", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("all", "reconcile", "automatic"), default="all")
    args = parser.parse_args()
    try:
        before = running_v1()
        candidate = build_failing_candidate()
        check(candidate != before["current_image_id"], "The test image must differ from the running release")
        if args.stage in ("all", "reconcile"):
            before = exercise_reconciliation(before, candidate)
        if args.stage in ("all", "automatic"):
            exercise_automatic_recovery(before, candidate)
    except KeyboardInterrupt:
        print("ACCEPTANCE INTERRUPTED. Inspect toolkit status before another mutation.", file=sys.stderr)
        return ExitCode.INTERRUPTED
    except (AcceptanceError, InspectionError, StateUncertain) as error:
        print(f"ACCEPTANCE STOPPED: {error}. Inspect toolkit status before another mutation.", file=sys.stderr)
        return 1
    except (OSError, KeyError, TypeError):
        print("ACCEPTANCE STOPPED: local files or metadata were unavailable. Inspect toolkit status.", file=sys.stderr)
        return 1
    print(f"PASS: Phase 3 acceptance stage {args.stage} completed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
