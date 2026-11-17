import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import time


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
            process = subprocess.Popen(
                ["docker", *arguments], cwd=self.root, env=self.environment,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                start_new_session=True,
            )
        except OSError:
            raise InspectionError("Could not launch Docker; check installation and project directory") from None
        deadline = time.monotonic() + self.timeout
        output = bytearray()
        total = 0
        try:
            with selectors.DefaultSelector() as selector:
                for stream in (process.stdout, process.stderr):
                    os.set_blocking(stream.fileno(), False)
                    selector.register(stream, selectors.EVENT_READ)
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise InspectionError("Docker inspection timed out; no toolkit mutation was requested")
                    for key, _ in selector.select(min(remaining, 0.1)):
                        chunk = os.read(key.fileobj.fileno(), 65536)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        total += len(chunk)
                        if total > 1024 * 1024:
                            raise InspectionError("Docker inspection output exceeded the 1 MiB limit")
                        if key.fileobj is process.stdout:
                            output.extend(chunk)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise InspectionError("Docker inspection timed out")
                try:
                    code = process.wait(timeout=remaining)
                except subprocess.TimeoutExpired:
                    raise InspectionError("Docker inspection timed out") from None
            if code:
                raise InspectionError("Docker inspection command failed; raw output withheld to avoid exposing configuration")
            try:
                return output.decode("utf-8")
            except UnicodeDecodeError:
                raise InspectionError("Docker returned invalid text") from None
        except OSError:
            raise InspectionError("Docker inspection I/O failed; no toolkit mutation was requested") from None
        finally:
            try:
                # Include ordinary child processes such as the Compose plugin.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                raise InspectionError("Local Docker command cleanup could not be confirmed") from None
            finally:
                process.stdout.close()
                process.stderr.close()

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
