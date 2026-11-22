"""Inspect or close a pending operation without requesting a Docker mutation."""
from pathlib import Path
import sys

from .config import DeploymentRequest, ExitCode, Settings
from .deploy import configuration_snapshot, require_same_configuration
from .docker import Docker, InspectionError
from .locking import LockBusy
from .override import override_path, read_override, write_override
from .preflight import LABEL, check_resources, containers, inspect_preflight, require, require_demo_user
from .recovery import history
from .state import RecordError, StateUncertain, operation_session, read_state


def pending_operation(latest, operation_id):
    if not latest or latest["status"] != "pending" or latest["id"] != operation_id:
        raise StateUncertain("The selected ID is not the latest pending operation")
    return latest


def observe_pending(root, docker, pending):
    docker.connect()
    pending_image = pending["image_id"] if pending.get("action") == "replace" else None
    api = check_resources(containers(docker), root, pending_image=pending_image)["api"]
    current_image = api["Image"]
    request = DeploymentRequest(current_image, pending["release"], Settings())
    observed = inspect_preflight(request, root, docker, pending_image=pending_image)
    require(observed["current_image_id"] == current_image and observed["api_id"] == api["Id"]
            and observed["api_running"] == api["State"]["Running"]
            and observed["api_started_at"] == api["State"].get("StartedAt"),
            "API changed during reconciliation inspection")
    require_demo_user(docker, current_image)
    override = read_override(root)
    labels = api["Config"]["Labels"]
    toolkit_files = f"{root / 'compose.yaml'},{override_path(root)}"
    repair = labels[LABEL + "project.config_files"] == toolkit_files and override != current_image
    require(not repair or (pending_image is not None and override == pending_image),
            "API image differs from toolkit override")
    return observed, override, repair


def show_observation(pending, observation, repair):
    running = "running" if observation["api_running"] else "exited"
    print(f"PENDING OPERATION: {pending['id']} intended_image={pending['image_id']}")
    print(f"OBSERVED API: id={observation['api_id']} image={observation['current_image_id']} state={running}")
    if repair:
        print("The pending override points at the intended image. Closure would align it with the observed API image.")


def reconcile(operation_id, *, close=False, root=None):
    root = Path(root or Path.cwd()).resolve()
    try:
        selected = pending_operation(read_state(root)["latest"], operation_id)
        if not close:
            history(root, allow_pending=True)
            observation, _, repair = observe_pending(root, Docker(root), selected)
            show_observation(selected, observation, repair)
            print("PREVIEW: inspect the stack and confirm any Docker changes have stopped before closing as unknown.")
            return ExitCode.OK

        with operation_session(root, allow_pending=True) as journal:
            pending = pending_operation(journal.latest, operation_id)
            history(root, allow_pending=True)
            initial = configuration_snapshot(root)
            docker = Docker(root)
            first = observe_pending(root, docker, pending)
            observation, _, repair = first
            require(observe_pending(root, docker, pending) == first, "Resources changed during reconciliation")
            require_same_configuration(root, initial)
            show_observation(pending, observation, repair)
            image = observation["current_image_id"]
            if repair:
                write_override(root, image)
                require(observe_pending(root, docker, pending) == (observation, image, False),
                        "Resources changed during override repair")
                require_same_configuration(root, initial)
            journal.close_unknown(operation_id, {
                "api_id": observation["api_id"],
                "image_id": image,
                "running": observation["api_running"],
            })
        print("RECONCILED: operation closed as unknown. The previous recorded success is retained.")
        return ExitCode.OK
    except LockBusy:
        print("LOCKED: another toolkit operation holds the lock.", file=sys.stderr)
        return ExitCode.LOCKED
    except RecordError:
        print("RECORDING FAILED: inspect status before retrying reconciliation.", file=sys.stderr)
        return ExitCode.RECORD_FAILED
    except (StateUncertain, InspectionError) as error:
        print(f"RECONCILIATION REFUSED: {error}", file=sys.stderr)
        return ExitCode.STATE_UNCERTAIN
    except (KeyError, TypeError, AttributeError, IndexError):
        print("RECONCILIATION REFUSED: unsupported resource metadata.", file=sys.stderr)
        return ExitCode.STATE_UNCERTAIN
    except KeyboardInterrupt:
        print("INTERRUPTED: inspect status before retrying reconciliation.", file=sys.stderr)
        return ExitCode.INTERRUPTED
