import argparse
import sys

from .config import ConfigurationError, DeploymentRequest, ExitCode, Settings
from .docker import InspectionError
from .preflight import inspect_preflight, inspect_status


def build_parser():
    parser = argparse.ArgumentParser(
        prog="python -m toolkit",
        description="Catalogue deployment toolkit. Batch B adds read-only Docker inspection.",
        allow_abbrev=False,
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "status", help="Inspect project container states; does not verify application health.",
        allow_abbrev=False,
    )
    for command, description in (
        ("validate", "Validate deployment inputs without contacting Docker."),
        ("preflight", "Inspect the candidate image and existing demo resources without changing them."),
        ("deploy", "Reserved for deployment (not implemented)."),
    ):
        child = commands.add_parser(command, help=description, allow_abbrev=False)
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
    if args.command == "status":
        try:
            rows = inspect_status()
        except (InspectionError, KeyError, TypeError, AttributeError, IndexError):
            print("INSPECTION FAILED: check local Docker access and project metadata; no health conclusion is available.", file=sys.stderr)
            return ExitCode.PREFLIGHT_REFUSED
        if not rows:
            print("STATUS: no sdt-demo containers found.")
        for row in rows:
            print(f"{row['service']}: {row['state']} image={row['image_id']}")
        print("OBSERVATION ONLY: ownership, HTTP behavior and operation state are not verified by status.")
        return ExitCode.OK
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
    if args.command == "deploy":
        print("UNAVAILABLE: deployment is not implemented in Batch B; nothing was changed.", file=sys.stderr)
        return ExitCode.UNAVAILABLE
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
