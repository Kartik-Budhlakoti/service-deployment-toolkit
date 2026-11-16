import argparse
import sys

from .config import ConfigurationError, DeploymentRequest, ExitCode, Settings


def build_parser():
    parser = argparse.ArgumentParser(
        prog="python -m toolkit",
        description="Catalogue deployment toolkit. Batch A validates inputs only.",
        allow_abbrev=False,
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "status", help="Reserved for read-only Docker/state inspection (not implemented).",
        allow_abbrev=False,
    )
    for command, description in (
        ("validate", "Validate deployment inputs without contacting Docker."),
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
        print("UNAVAILABLE: status inspection is not implemented in Batch A.", file=sys.stderr)
        return ExitCode.UNAVAILABLE
    try:
        settings = Settings(
            verification_timeout=args.verification_timeout,
            request_timeout=args.request_timeout,
            retry_interval=args.retry_interval,
            command_timeout=args.command_timeout,
        )
        DeploymentRequest(args.image, args.release, settings)
    except ConfigurationError as error:
        print(f"INVALID INPUT: {error}", file=sys.stderr)
        return ExitCode.INVALID_INPUT
    if args.command == "deploy":
        print("UNAVAILABLE: deployment is not implemented in Batch A; nothing was changed.", file=sys.stderr)
        return ExitCode.UNAVAILABLE
    print("VALID INPUT: Docker, image availability and project resources have NOT been checked.")
    return ExitCode.OK
