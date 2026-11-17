import hashlib
from pathlib import Path
import stat
import sys

from .checks import verify
from .config import DeploymentRequest, ExitCode
from .docker import Docker, InspectionError
from .locking import LockBusy
from .override import override_path, read_override, write_override
from .preflight import inspect_preflight, require, single
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


def validate_replacement_config(docker, root):
    config = docker.compose("config", "--format", "json")
    try:
        api = config["services"]["api"]
        allowed = {"build", "image", "environment", "ports", "networks", "depends_on",
                   "healthcheck", "read_only", "cap_drop", "security_opt",
                   "command", "entrypoint"}
        require(set(api) <= allowed, "Unsupported API deployment configuration")
        require(api.get("command") is None and api.get("entrypoint") is None,
                "API command and entrypoint overrides are unsupported")
        require(api.get("read_only") is True and api.get("cap_drop") == ["ALL"]
                and api.get("security_opt") == ["no-new-privileges:true"],
                "Expected API hardening is missing")
        require(set(api.get("environment", {})) == {"DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD"},
                "Unsupported API environment settings")
        require(api["environment"]["DB_HOST"] == "db"
                and api["environment"]["DB_NAME"] == "catalogue"
                and api["environment"]["DB_USER"] == "catalogue_reader",
                "Unexpected API database configuration")
    except (KeyError, TypeError, AttributeError):
        raise InspectionError("Unsupported API deployment configuration") from None


def describe(result):
    return ", ".join(name + "=" + ("pass" if passed else "not-passed")
                     for name, passed in result.checks.items())


def deploy(request, root=None):
    root = Path(root or Path.cwd()).resolve()
    # Reject the wrong directory without creating a journal there.
    try:
        initial = configuration_snapshot(root)
        docker = Docker(root, request.settings.command_timeout)
    except InspectionError as error:
        print(f"PREFLIGHT REFUSED: {error}", file=sys.stderr)
        return ExitCode.PREFLIGHT_REFUSED
    begun = False
    try:
        with operation_session(root) as journal:
            before = inspect_preflight(request, root, docker)
            read_override(root)
            validate_replacement_config(docker, root)
            image = before["candidate_image_id"]
            candidate = single(docker.json("image", "inspect", image), "candidate image")
            require((candidate.get("Config") or {}).get("User") == "10001:10001",
                    "Candidate must retain the demo non-root user 10001:10001")
            fixed = DeploymentRequest(image, request.release, request.settings)
            require_same_configuration(root, initial)
            # Resolve once, then use that immutable identity for the second snapshot and up.
            fresh = inspect_preflight(fixed, root, docker)
            require(fresh == before, "Project resources changed during preflight")
            action = "verify-only" if before["api_running"] and before["current_image_id"] == image else "replace"
            operation = journal.begin(image, request.release, action=action)
            begun = True
            print(f"OPERATION: {operation} action={action} image={image}")
            if action == "replace":
                write_override(root, image)
                require_same_configuration(root, initial)
                try:
                    run_command(replacement_arguments(root), root, docker.environment,
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
            journal.finish(operation, "succeeded" if result.passed else "failed", checks=result.checks)
            print("CHECKS: " + describe(result))
            if result.passed:
                print(f"SUCCESS: {action} verified and recorded; point-in-time checks only.")
                return ExitCode.OK
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
