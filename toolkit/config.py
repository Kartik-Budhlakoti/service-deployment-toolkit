from dataclasses import dataclass
from enum import IntEnum
import re


class ExitCode(IntEnum):
    OK = 0
    DEPLOYMENT_FAILED = 1
    INVALID_INPUT = 2
    UNAVAILABLE = 3
    PREFLIGHT_REFUSED = 4
    LOCKED = 5
    STATE_UNCERTAIN = 6
    RECORD_FAILED = 7
    INTERRUPTED = 130


class ConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class Settings:
    project: str = "sdt-demo"
    service: str = "api"
    compose_file: str = "compose.yaml"
    state_directory: str = ".runtime/toolkit"
    direct_url: str = "http://127.0.0.1:8089"
    proxy_url: str = "http://127.0.0.1:8088"
    verification_timeout: int = 60
    request_timeout: int = 3
    retry_interval: int = 1
    command_timeout: int = 60

    def __post_init__(self):
        limits = {
            "verification_timeout": (self.verification_timeout, 1, 600),
            "request_timeout": (self.request_timeout, 1, 30),
            "retry_interval": (self.retry_interval, 1, 30),
            "command_timeout": (self.command_timeout, 1, 300),
        }
        for name, (value, minimum, maximum) in limits.items():
            if type(value) is not int or not minimum <= value <= maximum:
                raise ConfigurationError(
                    f"{name} must be an integer from {minimum} to {maximum}"
                )
        if self.request_timeout > self.verification_timeout:
            raise ConfigurationError("request timeout exceeds verification timeout")
        if self.retry_interval >= self.verification_timeout:
            raise ConfigurationError("retry interval must be below verification timeout")


def validate_image(value: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 255:
        raise ConfigurationError("image reference must contain 1 to 255 characters")
    if re.fullmatch(r"sha256:[0-9a-f]{64}", value):
        return value
    if value.startswith("sha256:"):
        raise ConfigurationError("image IDs require sha256 and 64 lowercase hex digits")
    if not re.fullmatch(r"[a-z0-9][A-Za-z0-9._:/@-]*", value):
        raise ConfigurationError("image reference contains unsupported characters")
    name = value
    if "@" in value:
        name, separator, digest = value.partition("@")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            raise ConfigurationError("image digest must use sha256 and 64 lowercase hex digits")
    else:
        final_component = name.rsplit("/", 1)[-1]
        if ":" not in final_component:
            raise ConfigurationError("use an explicit image tag, digest, or full image ID")
    if not name or name.endswith(("/", ":")) or "//" in name:
        raise ConfigurationError("image name is incomplete")
    return value


def validate_release(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", value):
        raise ConfigurationError(
            "release must be 1 to 64 letters, digits, dots, underscores or hyphens; "
            "the first character must be a letter or digit"
        )
    return value


@dataclass(frozen=True)
class DeploymentRequest:
    image: str
    release: str
    settings: Settings

    def __post_init__(self):
        validate_image(self.image)
        validate_release(self.release)
