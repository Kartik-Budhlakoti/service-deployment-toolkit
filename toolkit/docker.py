import json
import os
from pathlib import Path

from .processes import CommandError, run_command


class InspectionError(RuntimeError):
    pass


class Docker:
    """Read-only commands against the explicitly selected local default context."""

    def __init__(self, root, timeout=60):
        self.root = Path(root).resolve()
        self.timeout = timeout
        self.environment = dict(os.environ)
        overrides = ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_TLS", "DOCKER_TLS_VERIFY",
                     "DOCKER_CERT_PATH", "DOCKER_API_VERSION", "COMPOSE_FILE",
                     "COMPOSE_PROJECT_NAME", "COMPOSE_PROFILES", "COMPOSE_ENV_FILES")
        if any(self.environment.get(name) for name in overrides):
            raise InspectionError("Docker/Compose environment overrides are unsupported; use a clean shell configuration")
        self.environment["COMPOSE_DISABLE_ENV_FILE"] = "1"
        self.environment["DOCKER_CLI_HINTS"] = "false"

    def _run(self, arguments):
        try:
            return run_command(["docker", *arguments], self.root, self.environment, self.timeout)
        except CommandError as error:
            raise InspectionError(str(error)) from None

    def text(self, *arguments):
        return self._run(["--context", "default", *arguments]).strip()

    def json(self, *arguments):
        try:
            return json.loads(self.text(*arguments))
        except (ValueError, RecursionError):
            raise InspectionError("Docker returned malformed JSON") from None

    def connect(self):
        if self._run(["context", "show"]).strip() != "default":
            raise InspectionError("Select the default local Docker context before inspection")
        context = self.json("context", "inspect", "default")
        try:
            endpoint = context[0]["Endpoints"]["docker"]["Host"]
        except (KeyError, IndexError, TypeError):
            raise InspectionError("Docker context metadata is incomplete") from None
        if endpoint != "unix:///var/run/docker.sock":
            raise InspectionError("Only the existing local /var/run/docker.sock endpoint is supported")
        info = self.json("info", "--format", "{{json .}}")
        if not isinstance(info, dict) or info.get("OSType") != "linux":
            raise InspectionError("A Linux Docker daemon is required")
        return info

    def compose(self, *arguments):
        if arguments != ("config", "--format", "json"):
            raise InspectionError("This Compose helper supports configuration inspection only")
        return self.json(
            "compose", "--project-directory", str(self.root),
            "--env-file", str(self.root / ".env"),
            "-p", "sdt-demo", "-f", str(self.root / "compose.yaml"),
            "--profile", "*", *arguments,
        )
