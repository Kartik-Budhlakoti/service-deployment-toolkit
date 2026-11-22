import argparse
import sys
import re

from .config import ConfigurationError, DeploymentRequest, ExitCode, Settings
from .docker import InspectionError
from .deploy import deploy
from .compatibility import CONTRACT
from .recovery import read_only
from .preflight import inspect_preflight, inspect_status
from .state import StateUncertain, read_state


def build_parser():
    parser = argparse.ArgumentParser(
        prog="python -m toolkit",
        description="Catalogue deployment toolkit. Inspect Docker and local operation records.",
        allow_abbrev=False,
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "status", help="Inspect local operation records and observe project containers.",
        allow_abbrev=False,
    )
    commands.add_parser("targets", help="List successful records and strict recovery eligibility.", allow_abbrev=False)
    rollback = commands.add_parser("rollback", help="Recover an explicitly selected verified release.", allow_abbrev=False)
    rollback.add_argument("--to", required=True, metavar="OPERATION_ID")
    rollback.add_argument("--dry-run", action="store_true")
    rollback.add_argument("--allow-equivalent-config", action="store_true",
                          help="Allow only an equivalent supported representation of the base Compose file.")
    for command, description in (
        ("validate", "Validate deployment inputs without contacting Docker."),
        ("preflight", "Inspect the candidate image and existing demo resources without changing them."),
        ("baseline", "Verify the running release and record its declared schema contract."),
        ("deploy", "Deploy or verify a local image; no automatic rollback."),
    ):
        child = commands.add_parser(command, help=description, allow_abbrev=False)
        if command == "baseline":
            child.add_argument("--schema", required=True, choices=(CONTRACT,))
        child.add_argument("--image", required=True, help="Explicit local tag, digest or full image ID.")
        child.add_argument("--release", required=True, help="Expected /version release string.")
        child.add_argument("--verification-timeout", type=int, default=60, metavar="SECONDS")
        child.add_argument("--request-timeout", type=int, default=3, metavar="SECONDS")
        child.add_argument("--retry-interval", type=int, default=1, metavar="SECONDS")
        child.add_argument("--command-timeout", type=int, default=60, metavar="SECONDS")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "targets":
        return read_only()
    if args.command == "rollback":
        if not re.fullmatch("[0-9a-f]{32}", args.to):
            parser.error("--to requires one full recorded operation ID (32 lowercase hexadecimal characters)")
        if args.dry_run:
            return read_only(args.to, args.allow_equivalent_config)
        return deploy(target=args.to, allow=args.allow_equivalent_config)
    if args.command == "status":
        state_code = ExitCode.OK
        try:
            state = read_state()
        except StateUncertain as error:
            print(f"STATE UNCERTAIN: {error}", file=sys.stderr)
            state_code = ExitCode.STATE_UNCERTAIN
        else:
            latest = state["latest"]
            if latest is None:
                print("OPERATION STATE: no recorded operations.")
            else:
                print(f"LATEST OPERATION: {latest['id']} {latest['status']} "
                      f"release={latest['release']} image={latest['image_id']} "
                      f"action={latest.get('action', 'legacy-unspecified')}")
                if latest["status"] == "pending":
                    print("STATE UNCERTAIN: an unfinished operation requires inspection.", file=sys.stderr)
                    state_code = ExitCode.STATE_UNCERTAIN
                if "recovery" in latest:
                    meta = latest["recovery"]
                    print(f"RECOVERY: {meta['kind']} target={meta['target']} "
                          f"exception_requested={meta['requested']} exception_needed={meta['needed']}")
            success = state["last_success"]
            if success is not None:
                print(f"LAST RECORDED SUCCESS: release={success['release']} image={success['image_id']}")
        try:
            rows = inspect_status()
        except (InspectionError, KeyError, TypeError, AttributeError, IndexError):
            print("INSPECTION FAILED: check local Docker access and project metadata; no health conclusion is available.", file=sys.stderr)
            return state_code or ExitCode.PREFLIGHT_REFUSED
        if not rows:
            print("STATUS: no sdt-demo containers found.")
        for row in rows:
            print(f"{row['service']}: {row['state']} image={row['image_id']}")
        print("OBSERVATION ONLY: container states and local records are point-in-time observations.")
        return state_code
    try:
        settings = Settings(
            verification_timeout=args.verification_timeout,
            request_timeout=args.request_timeout,
            retry_interval=args.retry_interval,
            command_timeout=args.command_timeout,
        )
        request = DeploymentRequest(args.image, args.release, settings)
    except ConfigurationError as error:
        print(f"INVALID INPUT: {error}", file=sys.stderr)
        return ExitCode.INVALID_INPUT
    if args.command == "baseline":
        return deploy(request, baseline=True)
    if args.command == "deploy":
        return deploy(request)
    if args.command == "preflight":
        try:
            result = inspect_preflight(request)
        except InspectionError as error:
            print(f"PREFLIGHT REFUSED: {error}", file=sys.stderr)
            return ExitCode.PREFLIGHT_REFUSED
        print(f"PREFLIGHT PASSED: candidate image={result['candidate_image_id']}")
        print(f"Current API image={result['current_image_id']}")
        print("READ-ONLY SNAPSHOT: release content, HTTP behavior, lock and operation state are not verified yet.")
        return ExitCode.OK
    print("VALID INPUT: Docker, image availability and project resources have NOT been checked.")
    return ExitCode.OK
