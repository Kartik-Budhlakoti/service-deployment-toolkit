"""Exercise manual recovery on the owner's dedicated demo after saving a baseline."""
import argparse
from contextlib import contextmanager
import os
from pathlib import Path
import secrets
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from toolkit.config import DeploymentRequest, Settings
from toolkit.docker import InspectionError
from toolkit.preflight import inspect_preflight
from toolkit.recovery import history, target_record
from toolkit.state import StateUncertain, read_state


def check(value, message):
    if not value:
        raise RuntimeError(message)


def cli(*args, expected=0, environment=None):
    result = subprocess.run([sys.executable, "-m", "toolkit", *args], cwd=ROOT, env=environment)
    check(result.returncode == expected, f"Expected exit {expected}, observed {result.returncode}")


def inspect(image, release):
    return inspect_preflight(DeploymentRequest(image, release, Settings()), ROOT)


@contextmanager
def comment_edit():
    path = ROOT / "compose.yaml"
    original = path.read_bytes()
    changed = original + b"\n# Temporary Phase 3 recovery acceptance comment\n"
    # Keep the same inode and permissions and preserve concurrent editor changes.
    with path.open("r+b") as file:
        check(file.read() == original, "Compose file changed before exercise")
        file.write(changed[len(original):])
        file.flush()
        os.fsync(file.fileno())
    try:
        yield
    finally:
        with path.open("r+b") as file:
            check(file.read() == changed, "Compose file changed externally. Inspect it before restoring the comment.")
            file.truncate(len(original))
            file.flush()
            os.fsync(file.fileno())


def exercise(target, candidate):
    record = target_record(history(ROOT), target)
    check(record["release"] == "demo-v1", "Select the demo-v1 baseline for this exercise")
    image = record["image_id"]
    start = inspect(image, "demo-v1")
    check(start["api_running"] and start["current_image_id"] == image, "Start this exercise on the recorded running v1")
    v2 = inspect(candidate, "demo-v2")["candidate_image_id"]
    check(v2 != image, "Supply the separate demo-v2 test image from Phase 2")
    subprocess.run([sys.executable, "tests/smoke.py"], cwd=ROOT, check=True)
    args = ["rollback", "--to", target]
    cli(*args, "--dry-run")
    before = read_state(ROOT)
    with comment_edit():
        cli(*args, "--dry-run", expected=4)
        cli(*args, "--dry-run", "--allow-equivalent-config")
        changed = dict(os.environ, APP_DB_PASSWORD=secrets.token_hex(32))
        cli(*args, "--dry-run", expected=4, environment=changed)
        cli(*args, "--dry-run", "--allow-equivalent-config", expected=4, environment=changed)
        cli(*args, "--allow-equivalent-config", expected=4, environment=changed)
        check(read_state(ROOT) == before, "A preview or refused attempt changed the journal")
        check(inspect(image, "demo-v1") == start, "A preview or refused attempt changed the stack")
        print("PASS: comment and environment-change eligibility gates", flush=True)
        cli("deploy", "--image", v2, "--release", "demo-v2")
        deployed = inspect(v2, "demo-v2")
        check(deployed["current_image_id"] == v2 and deployed["api_id"] != start["api_id"]
              and deployed["dependency_ids"] == start["dependency_ids"], "Candidate deployment identity changed unexpectedly")
        cli(*args, "--allow-equivalent-config")
        latest = read_state(ROOT)["latest"]
        check(latest["status"] == "succeeded" and latest["action"] == "replace"
              and latest["image_id"] == image and latest["release"] == "demo-v1"
              and latest["recovery"] == dict(kind="rollback", target=target, requested=True, needed=True),
              "Rollback outcome or target attribution differs")
    final = inspect(image, "demo-v1")
    check(final["api_running"] and final["api_id"] != deployed["api_id"] and final["current_image_id"] == image
          and final["dependency_ids"] == start["dependency_ids"], "Final container identities differ")
    cli(*args, "--dry-run")
    subprocess.run([sys.executable, "tests/smoke.py"], cwd=ROOT, check=True)
    print("PASS: selected v1 restored and verified, dependency IDs retained, original Compose bytes restored")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--to", required=True, help="Full ID of your new demo-v1 baseline.")
    parser.add_argument("--candidate", required=True, help="Separate, trusted local demo-v2 image.")
    args = parser.parse_args()
    try:
        exercise(args.to, args.candidate)
    except (InspectionError, StateUncertain, OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Exercise stopped: {exc}. Inspect toolkit status before another mutation.", file=sys.stderr)
        sys.exit(1)
