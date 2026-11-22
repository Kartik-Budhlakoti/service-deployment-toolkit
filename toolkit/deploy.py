import hashlib
from pathlib import Path
import stat
import sys

from .checks import verify
from .config import DeploymentRequest, ExitCode, Settings
from .compatibility import check_plan, comparison_key, compose_arguments, observe, read_inputs, signed
from .recovery import evidence, history, inspect_target, target_record
from .docker import Docker, InspectionError
from .locking import LockBusy
from .override import override_path, read_override, write_override
from .preflight import inspect_preflight, require, require_demo_user, validate_replacement_config
from .processes import CommandError, run_command
from .state import RecordError, StateUncertain, operation_session


OBSERVATION_SECONDS = 10


def configuration_snapshot(root):
    hashes = []
    try:
        for name in ("compose.yaml", ".env", "demo/nginx/default.conf"):
            path = root / name
            if not stat.S_ISREG(path.lstat().st_mode):
                raise ValueError
            with path.open("rb") as file:
                data = file.read(1048577)
            if len(data) > 1048576:
                raise ValueError
            hashes.append(hashlib.sha256(data).digest())
    except (OSError, ValueError):
        raise InspectionError("Deployment configuration is missing or unsupported") from None
    return tuple(hashes)  # Includes secrets: keep only in memory, never in reports.


def require_same_configuration(root, before):
    require(configuration_snapshot(root) == before, "Configuration changed during this operation")


def replacement_arguments(root):
    return ["docker", "--context", "default", "compose", "--project-directory", str(root),
            "--env-file", str(root / ".env"), "-p", "sdt-demo", "-f", str(root / "compose.yaml"),
            "-f", str(override_path(root)), "up", "-d", "--no-deps", "--no-build",
            "--pull", "never", "--force-recreate", "api"]


def describe(result):
    return ", ".join(name + "=" + ("pass" if passed else "not-passed")
                     for name, passed in result.checks.items())


def deploy(request=None, root=None, *, baseline=False, target=None, allow=False):
    root = Path(root or Path.cwd()).resolve()
    # Reject the wrong directory without creating a journal there.
    try:
        initial = configuration_snapshot(root)
        docker = Docker(root, (request.settings if request else Settings()).command_timeout)
    except InspectionError as error:
        print(f"PREFLIGHT REFUSED: {error}", file=sys.stderr)
        return ExitCode.PREFLIGHT_REFUSED
    begun = False
    try:
        with operation_session(root) as journal:
            recovery = None
            if baseline or target is not None:
                read_inputs(root, docker)
                records = history(root)
                if target is not None:
                    record = target_record(records, target)
                    request, key, snapshot, needed = inspect_target(root, docker, record, allow)
                    recovery = dict(kind="rollback", target=target, requested=allow, needed=needed)
                else:
                    # A lost key must never be silently replaced while its evidence survives.
                    key = comparison_key(root, create=not any(r.get("evidence") for r in records.values()))
                    recovery = dict(kind="baseline", target=None, requested=False, needed=False)
            before = inspect_preflight(request, root, docker)
            read_override(root)
            validate_replacement_config(docker, root)
            image = before["candidate_image_id"]
            require_demo_user(docker, image)
            fixed = DeploymentRequest(image, request.release, request.settings)
            require_same_configuration(root, initial)
            # Resolve once, then use that immutable identity for the second snapshot and up.
            fresh = inspect_preflight(fixed, root, docker)
            require(fresh == before, "Project resources changed during preflight")
            action = "verify-only" if before["api_running"] and before["current_image_id"] == image else "replace"
            if recovery:
                if baseline:
                    require(action == "verify-only", "Baseline requires the already running image")
                current = observe(root, docker, key, image)
                if target is not None:
                    require(current == snapshot, "Recovery inputs changed during selection")
                snapshot = current
            operation = journal.begin(image, request.release, action=action, recovery=recovery)
            begun = True
            print(f"OPERATION: {operation} action={action} image={image}")
            if target is not None:
                print(f"RECOVERY TARGET: {target} exception_requested={allow} "
                      f"exception_needed={recovery['needed']}")
            if action == "replace":
                if recovery:
                    require(observe(root, docker, key, image) == snapshot,
                            "Recovery inputs changed before replacement")
                write_override(root, image)
                require_same_configuration(root, initial)
                try:
                    arguments = replacement_arguments(root)
                    if recovery:
                        base_model = docker.compose("config", "--format", "json")
                        require(signed(key, "model", base_model) == snapshot["model"], "Resolved model changed before replacement")
                        check_plan(docker, root, base_model, image, installed=True)
                        require_same_configuration(root, initial)
                        arguments = compose_arguments(root, override_path(root)) + arguments[-8:]
                    run_command(arguments, root, docker.environment,
                                request.settings.command_timeout)
                except CommandError:
                    print("STATE UNCERTAIN: replacement command did not confirm completion; pending intent retained.",
                          file=sys.stderr)
                    observation = verify(fixed, root, docker, image, before["dependency_ids"],
                                         duration=OBSERVATION_SECONDS)
                    print("OBSERVATION ONLY: " + describe(observation))
                    print("No retry or rollback requested; reconciliation is required.", file=sys.stderr)
                    return ExitCode.STATE_UNCERTAIN
            result = verify(fixed, root, docker, image, before["dependency_ids"])
            require_same_configuration(root, initial)
            proof = None
            if recovery and result.passed:
                require(comparison_key(root) == key, "Comparison key changed during verification")
                after = inspect_preflight(fixed, root, docker)
                require(after["current_image_id"] == image and after["api_running"]
                        and after["dependency_ids"] == before["dependency_ids"]
                        and (action != "verify-only" or after["api_id"] == before["api_id"]),
                        "Runtime changed during recovery verification")
                require(observe(root, docker, key, image) == snapshot,
                        "Recovery inputs changed during verification")
                proof = evidence(key, operation, image, request.release, snapshot)
            journal.finish(operation, "succeeded" if result.passed else "failed",
                           checks=result.checks, evidence=proof)
            print("CHECKS: " + describe(result))
            if result.passed:
                print(f"SUCCESS: {action} verified and recorded; point-in-time checks only.")
                return ExitCode.OK
            if target is not None:
                print("RECOVERY VERIFICATION FAILED: attempt recorded as failed; inspect the current API.", file=sys.stderr)
            else:
                print("VERIFICATION FAILED: recorded failure; no rollback requested.", file=sys.stderr)
            return ExitCode.DEPLOYMENT_FAILED
    except LockBusy:
        print("LOCKED: another toolkit operation holds the lock.", file=sys.stderr)
        return ExitCode.LOCKED
    except RecordError:
        print("RECORDING FAILED: inspect local operation state; do not assume success or repeat deployment.", file=sys.stderr)
        return ExitCode.RECORD_FAILED
    except StateUncertain:
        print("STATE UNCERTAIN: inspect local records before another mutation.", file=sys.stderr)
        return ExitCode.STATE_UNCERTAIN
    except InspectionError as error:
        prefix = "STATE UNCERTAIN" if begun else "PREFLIGHT REFUSED"
        print(f"{prefix}: {error}", file=sys.stderr)
        return ExitCode.STATE_UNCERTAIN if begun else ExitCode.PREFLIGHT_REFUSED
    except KeyboardInterrupt:
        print("INTERRUPTED: pending intent, if created, is retained; inspect before retrying.", file=sys.stderr)
        return ExitCode.INTERRUPTED
    except Exception:
        print("INTERNAL FAILURE: operation outcome is not confirmed; inspect before retrying.", file=sys.stderr)
        return ExitCode.STATE_UNCERTAIN
