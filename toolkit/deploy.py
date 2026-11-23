from dataclasses import dataclass
import hashlib
from pathlib import Path
import sys

from .checks import verify
from .config import DeploymentRequest, ExitCode, Settings
from .compatibility import (
    check_plan, comparison_key, compose_arguments, observe, read_inputs, regular_bytes, signed,
)
from .reports import incident_reports
from .recovery import evidence, history, inspect_target, target_record
from .docker import Docker, InspectionError
from .locking import LockBusy
from .override import override_path, read_override, write_override
from .preflight import inspect_preflight, require, require_demo_user, validate_replacement_config
from .processes import CommandError, run_command
from .state import RecordError, StateUncertain, operation_session


OBSERVATION_SECONDS = 10
UP_API = ["up", "-d", "--no-deps", "--no-build", "--pull", "never", "--force-recreate", "api"]


@dataclass(frozen=True)
class PreparedDeployment:
    request: DeploymentRequest
    before: dict
    action: str


def configuration_snapshot(root):
    try:
        # Includes secrets: keep only in memory, never in reports.
        return tuple(hashlib.sha256(regular_bytes(root / name)).digest()
                     for name in ("compose.yaml", ".env", "demo/nginx/default.conf"))
    except (OSError, InspectionError):
        raise InspectionError("Deployment configuration is missing or unsupported") from None


def require_same_configuration(root, before):
    require(configuration_snapshot(root) == before, "Configuration changed during this operation")


def replacement_arguments(root, *, all_profiles=False):
    arguments = compose_arguments(root, override_path(root))
    return (arguments if all_profiles else arguments[:-2]) + UP_API


def describe(result):
    return ", ".join(name + "=" + ("pass" if passed else "not-passed")
                     for name, passed in result.checks.items())


def prepare(request, root, docker, initial):
    before = inspect_preflight(request, root, docker)
    read_override(root)
    validate_replacement_config(docker, root)
    image = before["candidate_image_id"]
    require_demo_user(docker, image)
    fixed = DeploymentRequest(image, request.release, request.settings)
    require_same_configuration(root, initial)
    # Resolve once so the second inspection and replacement use the same local image.
    require(inspect_preflight(fixed, root, docker) == before,
            "Project resources changed during preflight")
    action = "verify-only" if before["api_running"] and before["current_image_id"] == image else "replace"
    return PreparedDeployment(fixed, before, action)


def require_compatible(prepared, root, docker, compatibility, *, installed=False):
    key, snapshot = compatibility
    image = prepared.request.image
    require(observe(root, docker, key, image, plan=not installed,
                    pending_image=image if installed else None) == snapshot,
            "Recovery inputs changed during the operation")
    require(comparison_key(root) == key, "Comparison key changed during the operation")


def api_instance(observation):
    return observation["api_id"], observation["api_started_at"]


def execute(journal, prepared, root, docker, initial, *, compatibility=None, recovery=None, auto_target=None):
    request, before, action = prepared.request, prepared.before, prepared.action
    image = request.image
    require_same_configuration(root, initial)
    operation = journal.begin(image, request.release, action=action,
                              recovery=recovery, auto_target=auto_target)
    print(f"OPERATION: {operation} action={action} image={image}")
    if recovery and recovery["target"]:
        print(f"RECOVERY TARGET: {recovery['target']} exception_requested={recovery['requested']} "
              f"exception_needed={recovery['needed']}")
        if "trigger" in recovery:
            print(f"AUTOMATIC RECOVERY FOR: {recovery['trigger']}")
    if auto_target:
        print(f"AUTOMATIC RECOVERY BASELINE: {auto_target}")

    if action == "replace":
        if compatibility:
            require_compatible(prepared, root, docker, compatibility)
            require(inspect_preflight(request, root, docker) == before,
                    "Project resources changed before replacement")
        write_override(root, image)
        if compatibility:
            key, snapshot = compatibility
            base_model = docker.compose("config", "--format", "json")
            require(signed(key, "model", base_model) == snapshot["model"],
                    "Resolved model changed before replacement")
            check_plan(docker, root, base_model, image, installed=True)
            # The stored override may differ from the current API only while
            # the matching replacement is pending.
            require_compatible(prepared, root, docker, compatibility, installed=True)
            require(inspect_preflight(request, root, docker, pending_image=image) == before
                    and read_override(root) == image, "Project resources changed before replacement")
        require_same_configuration(root, initial)
        try:
            run_command(replacement_arguments(root, all_profiles=compatibility is not None),
                        root, docker.environment, request.settings.command_timeout)
        except CommandError:
            print("STATE UNCERTAIN: replacement command did not confirm completion; pending intent retained.",
                  file=sys.stderr)
            observation = verify(request, root, docker, image, before["dependency_ids"],
                                 duration=OBSERVATION_SECONDS)
            if observation.trace is not None:
                journal.observe_unconfirmed(operation, observation.trace)
            print("OBSERVATION ONLY: " + describe(observation))
            print("Reconcile the pending operation before any retry or rollback.", file=sys.stderr)
            return ExitCode.STATE_UNCERTAIN, None

    expected_api = None
    if compatibility:
        observed = before
        if action == "replace":
            observed = inspect_preflight(request, root, docker)
            require(observed["current_image_id"] == image and observed["api_id"] != before["api_id"]
                    and observed["dependency_ids"] == before["dependency_ids"],
                    "Could not confirm the intended replacement API")
        expected_api = api_instance(observed)
    result = verify(request, root, docker, image, before["dependency_ids"], expected_api=expected_api)
    require_same_configuration(root, initial)
    proof = None
    if compatibility and result.passed:
        after = inspect_preflight(request, root, docker)
        require(after["current_image_id"] == image and after["api_running"]
                and after["dependency_ids"] == before["dependency_ids"]
                and api_instance(after) == expected_api,
                "Runtime changed during recovery verification")
        require_compatible(prepared, root, docker, compatibility)
        require(inspect_preflight(request, root, docker) == after,
                "Project resources changed while recording recovery evidence")
        key, snapshot = compatibility
        proof = evidence(key, operation, image, request.release, snapshot)
    journal.finish(operation, "succeeded" if result.passed else "failed",
                   checks=result.checks, evidence=proof, trace=None if result.passed else result.trace)
    print("CHECKS: " + describe(result))
    if result.passed:
        print(f"SUCCESS: {action} verified and recorded; point-in-time checks only.")
        return ExitCode.OK, expected_api
    if recovery and recovery["target"]:
        print("RECOVERY VERIFICATION FAILED: attempt recorded as failed; inspect the current API.", file=sys.stderr)
    else:
        print("VERIFICATION FAILED: deployment recorded as failed.", file=sys.stderr)
    return ExitCode.DEPLOYMENT_FAILED, expected_api


def automatic_baseline(journal, prepared, root, docker):
    previous = journal.last_success
    require(previous and previous.get("evidence"), "Register the running API as a recovery baseline first")
    before = prepared.before
    require(prepared.action == "replace" and before["api_running"]
            and before["current_image_id"] == previous["image_id"],
            "Automatic recovery requires a different candidate image and the recorded baseline running")
    records = history(root)
    previous = target_record(records, previous["id"])
    request, key, snapshot, _ = inspect_target(root, docker, previous, False, prepared.request.settings)
    current = inspect_preflight(request, root, docker)
    require(current["api_running"] and current["current_image_id"] == request.image
            and api_instance(current) == api_instance(before)
            and current["dependency_ids"] == before["dependency_ids"],
            "Running baseline changed during preflight")
    result = verify(request, root, docker, request.image, current["dependency_ids"],
                    expected_api=api_instance(current))
    require(result.passed, "Running baseline did not pass fresh verification")
    require_compatible(prepared, root, docker, (key, snapshot))
    require(inspect_preflight(prepared.request, root, docker) == before,
            "Project resources changed while verifying the baseline")
    return previous, (key, snapshot)


def attempt_automatic_recovery(journal, candidate, failed_api, previous, root, docker, initial):
    trigger = journal.latest["id"]
    try:
        require_same_configuration(root, initial)
        request, key, snapshot, _ = inspect_target(root, docker, previous, False, candidate.request.settings)
        target = prepare(request, root, docker, initial)
        require(target.before["current_image_id"] == candidate.request.image
                and api_instance(target.before) == failed_api
                and target.before["dependency_ids"] == candidate.before["dependency_ids"],
                "The failed replacement is no longer the expected current API")
        require_compatible(target, root, docker, (key, snapshot))
    except InspectionError as error:
        print(f"AUTOMATIC RECOVERY SKIPPED: {error}", file=sys.stderr)
        return ExitCode.DEPLOYMENT_FAILED

    recovery = dict(kind="automatic", target=previous["id"], trigger=trigger,
                    requested=False, needed=False)
    result, _ = execute(journal, target, root, docker, initial,
                        compatibility=(key, snapshot), recovery=recovery)
    if result in (ExitCode.OK, ExitCode.DEPLOYMENT_FAILED):
        outcome = "succeeded" if result == ExitCode.OK else "failed"
        print(f"AUTOMATIC RECOVERY: {outcome}; deployment {trigger} remains failed.")
        return ExitCode.DEPLOYMENT_FAILED
    return result


def deploy(request=None, root=None, *, baseline=False, target=None, allow=False, auto_recover=False):
    root = Path(root or Path.cwd()).resolve()
    journal = None
    try:
        initial = configuration_snapshot(root)
        docker = Docker(root, (request.settings if request else Settings()).command_timeout)
        with operation_session(root) as journal, incident_reports(root, journal):
            recovery = None
            compatibility = None
            if baseline or target is not None or auto_recover:
                read_inputs(root, docker)
            if target is not None:
                record = target_record(history(root), target)
                request, key, snapshot, needed = inspect_target(root, docker, record, allow)
                recovery = dict(kind="rollback", target=target, requested=allow, needed=needed)
                compatibility = key, snapshot

            prepared = prepare(request, root, docker, initial)
            if baseline:
                require(prepared.action == "verify-only", "Baseline requires the already running image")
                records = history(root)
                key = comparison_key(root, create=not any(r.get("evidence") for r in records.values()))
                compatibility = key, observe(root, docker, key, prepared.request.image)
                recovery = dict(kind="baseline", target=None, requested=False, needed=False)
            if auto_recover:
                previous, compatibility = automatic_baseline(journal, prepared, root, docker)
                result, observed_api = execute(journal, prepared, root, docker, initial,
                                               compatibility=compatibility, auto_target=previous["id"])
                if result == ExitCode.DEPLOYMENT_FAILED:
                    return attempt_automatic_recovery(journal, prepared, observed_api, previous,
                                                      root, docker, initial)
                return result
            if target is not None:
                require_compatible(prepared, root, docker, compatibility)
            result, _ = execute(journal, prepared, root, docker, initial,
                                compatibility=compatibility, recovery=recovery)
            return result
    except LockBusy:
        print("LOCKED: another toolkit operation holds the lock.", file=sys.stderr)
        return ExitCode.LOCKED
    except RecordError:
        print("RECORDING FAILED: inspect local operation state; do not assume success or repeat deployment.",
              file=sys.stderr)
        return ExitCode.RECORD_FAILED
    except StateUncertain as error:
        print(f"STATE UNCERTAIN: {error}", file=sys.stderr)
        return ExitCode.STATE_UNCERTAIN
    except InspectionError as error:
        pending = journal is not None and journal.latest and journal.latest["status"] == "pending"
        prefix = "STATE UNCERTAIN" if pending else "PREFLIGHT REFUSED"
        print(f"{prefix}: {error}", file=sys.stderr)
        return ExitCode.STATE_UNCERTAIN if pending else ExitCode.PREFLIGHT_REFUSED
    except KeyboardInterrupt:
        print("INTERRUPTED: inspect status before retrying.", file=sys.stderr)
        return ExitCode.INTERRUPTED
    except Exception:
        print("INTERNAL FAILURE: operation outcome is not confirmed; inspect before retrying.", file=sys.stderr)
        return ExitCode.STATE_UNCERTAIN
