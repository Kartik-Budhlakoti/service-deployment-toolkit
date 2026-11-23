"""Exercise diagnostics and incident reports on the dedicated demo."""
import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from toolkit.config import DeploymentRequest, Settings
from toolkit.docker import Docker, InspectionError
from toolkit.locking import LockBusy
from toolkit.preflight import inspect_preflight
from toolkit.recovery import history
from toolkit.state import RecordError, StateUncertain, operation_session, read_state

V1 = DeploymentRequest("sdt-demo-api:phase1", "demo-v1", Settings())
DNS = "api -> db (DNS/IPv4)"
TCP = "api -> db (TCP/5432)"
DIRECT = "host -> api (/items)"
PROXY = "host -> nginx (/items)"


class ExerciseFailed(RuntimeError):
    pass


def require(ok, message):
    if not ok:
        raise ExerciseFailed(message)


def diagnostics(expected):
    result = subprocess.run([sys.executable, "-m", "toolkit", "diagnose"], cwd=ROOT,
                            stdout=subprocess.PIPE, text=True)
    print(result.stdout, end="", flush=True)
    require(result.returncode == expected, f"diagnose returned {result.returncode}, expected {expected}")
    rows = {}
    for line in result.stdout.splitlines():
        match = re.fullmatch(r"(.+): ([a-z0-9-]+) \([0-9]+ ms\)", line)
        require(match is not None, "Unexpected diagnostic output")
        route, outcome = match.groups()
        require(route not in rows, "Duplicate diagnostic route")
        rows[route] = outcome
    require(set(rows) == {DNS, TCP, DIRECT, PROXY}, "Incomplete diagnostic output")
    return rows


def expect_outage(service, rows):
    if service == "nginx":
        require(rows == {DNS: "ok", TCP: "ok", DIRECT: "ok", PROXY: "skipped-container-exited"},
                "Expected only the proxy route to be unavailable")
    else:
        require(rows[TCP] == "skipped-no-running-db-address", "Expected no running database address")
        require(rows[DNS] in ("resolution-failed", "resolved-address-unconfirmed", "probe-unavailable"),
                "Unexpected database name observation")
        # DNS or a connection attempt can consume the HTTP worker's time budget.
        require(all(rows[r] in ("http-503", "timeout", "probe-unavailable") for r in (DIRECT, PROXY)),
                "Unexpected catalogue response during database outage")


def run(*args):
    subprocess.run([sys.executable, *args], cwd=ROOT, check=True)


def healthy(docker):
    live = inspect_preflight(V1, ROOT, docker)
    require(live["api_running"] and live["current_image_id"] == live["candidate_image_id"],
            "Start with the Phase 1 image running as demo-v1")
    run("tests/smoke.py")
    require(all(v == "ok" for v in diagnostics(0).values()), "Expected four healthy diagnostic routes")
    return live


@contextmanager
def stopped(docker, container_id):
    command = ["docker", "--context", "default", "container"]
    print(f"Temporarily stopping {container_id}", flush=True)
    try:
        subprocess.run([*command, "stop", container_id], cwd=ROOT, env=docker.environment,
                       timeout=60, check=True)
        yield
    finally:
        print(f"Starting original container {container_id}", flush=True)
        subprocess.run([*command, "start", container_id], cwd=ROOT, env=docker.environment,
                       timeout=60, check=True)


def confirm_restoration(docker, before):
    deadline = time.monotonic() + 60
    while True:
        try:
            after = inspect_preflight(V1, ROOT, docker)
            require(after == before, "API instance or dependency IDs changed during the outage")
            run("tests/smoke.py")
            break
        except (InspectionError, subprocess.CalledProcessError):
            if time.monotonic() >= deadline:
                raise
            time.sleep(1)
    require(all(v == "ok" for v in diagnostics(0).values()), "Diagnostic routes did not recover")


def dependency_outage(service):
    docker = Docker(ROOT)
    with operation_session(ROOT):
        original = read_state(ROOT)
        before = healthy(docker)
        target = before["dependency_ids"][service]
        require(inspect_preflight(V1, ROOT, docker) == before, "Resource identities changed before the stop")
        try:
            with stopped(docker, target):
                rows = diagnostics(1)
                expect_outage(service, rows)
                if service == "db":
                    run("tests/smoke.py", "--database-down")
        finally:
            confirm_restoration(docker, before)
            require(read_state(ROOT) == original, "The operation journal changed during diagnostics")
    print(f"PASS: {service} outage observed and same containers restored", flush=True)


def check_report(report, failed, recovered):
    require(report.get("version") == 1, "Unsupported report format")
    operation = report["operation"]
    recovery = report["automatic_recovery"]
    require(operation["id"] == failed["id"] and operation["outcome"] == failed["status"] == "failed"
            and operation["image_id"] == failed["image_id"] and operation["checks"] == failed["checks"],
            "Report does not describe the failed candidate")
    trace = operation["verification"]
    require(trace and trace == failed.get("verification_trace"), "Candidate samples missing or different")
    require(trace["first_failed"] and trace["last"], "Expected first and final candidate samples")
    require(any((sample["instance"] or {}).get("image_id") == failed["image_id"]
                for sample in trace.values()), "No retained sample identifies the candidate image")
    require(recovery and recovery["id"] == recovered["id"]
            and recovery["outcome"] == recovered["status"] == "succeeded"
            and recovery["image_id"] == recovered["image_id"] != failed["image_id"]
            and recovery["checks"] == recovered["checks"] and all(recovery["checks"].values())
            and recovery["recovery_request"] == recovered["recovery"]
            and recovery["recovery_request"]["trigger"] == operation["id"]
            and operation["automatic_target"] == recovery["recovery_request"]["target"],
            "Report recovery outcome or link differs from the journal")


def candidate():
    existing = set(history(ROOT))
    before = healthy(Docker(ROOT))
    run("scripts/phase3-final-acceptance.py", "--stage", "automatic")
    records = history(ROOT)
    latest = read_state(ROOT)["latest"]
    meta = latest.get("recovery", {})
    require(meta.get("kind") == "automatic" and latest["id"] not in existing
            and meta["trigger"] not in existing, "Expected a new automatic recovery and candidate")
    failed = records[meta["trigger"]]
    path = ROOT / "reports" / f"operation-{failed['id']}.json"
    report = json.loads(path.read_bytes())
    check_report(report, failed, latest)
    run("-m", "toolkit", "report", "--operation", latest["id"])
    require(json.loads(path.read_bytes()) == report, "Report changed during re-export")
    after = healthy(Docker(ROOT))
    require(before["dependency_ids"] == after["dependency_ids"]
            and after["current_image_id"] == latest["image_id"] == before["current_image_id"]
            and after["api_id"] != before["api_id"], "Unexpected restored stack identity")
    print(f"PASS: candidate {failed['id']} and recovery {latest['id']} verified against {path.name}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("database", "proxy", "candidate"))
    stage = parser.parse_args().stage
    try:
        if stage == "candidate":
            candidate()
        else:
            dependency_outage("db" if stage == "database" else "nginx")
    except KeyboardInterrupt:
        print("Interrupted. Inspect toolkit status and the demo containers before continuing.", file=sys.stderr)
        return 130
    except (ExerciseFailed, LockBusy, InspectionError, RecordError, StateUncertain, OSError,
            subprocess.SubprocessError, ValueError, TypeError, KeyError) as error:
        print(f"Exercise stopped: {error}. Inspect the demo before continuing.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
