from dataclasses import dataclass
from pathlib import Path
import sys
import time

from .docker import InspectionError
from .preflight import check_resources, containers
from .processes import CommandError, run_command
from .state import CHECK_NAMES


@dataclass(frozen=True)
class Verification:
    checks: dict
    attempts: int

    @property
    def passed(self):
        return all(self.checks.values())


def http_check(url, kind, release, timeout):
    try:
        result = run_command(
            [sys.executable, "-I", str(Path(__file__).with_name("http_probe.py")),
             url, kind, release, str(timeout)],
            Path(__file__).parent, None, timeout,
        )
        return result.strip() == "PASS"
    except CommandError:
        return False


class BudgetDocker:
    def __init__(self, docker, deadline, clock):
        self.docker, self.deadline, self.clock = docker, deadline, clock

    def _call(self, method, args):
        remaining = self.deadline - self.clock()
        if remaining <= 0:
            raise InspectionError("Verification deadline expired")
        previous = self.docker.timeout
        try:
            self.docker.timeout = min(previous, remaining)
            return getattr(self.docker, method)(*args)
        finally:
            self.docker.timeout = previous

    def json(self, *args):
        return self._call("json", args)

    def text(self, *args):
        return self._call("text", args)


def verify(request, root, docker, image, dependency_ids, duration=None,
           clock=time.monotonic, sleep=time.sleep, http=http_check):
    settings = request.settings
    deadline = clock() + (duration if duration is not None else settings.verification_timeout)
    bounded = BudgetDocker(docker, deadline, clock)
    result = {name: False for name in CHECK_NAMES}
    attempts = 0

    def get(path, kind, proxy=False):
        remaining = deadline - clock()
        if remaining <= 0:
            return False
        base = settings.proxy_url if proxy else settings.direct_url
        return http(base + path, kind, request.release, min(settings.request_timeout, remaining))

    def inspect():
        selected = check_resources(containers(bounded), root)
        if any(selected[name]["Id"] != value for name, value in dependency_ids.items()):
            raise InspectionError("Dependency container changed during verification")
        return selected["api"]

    while clock() < deadline:
        attempts += 1
        result = {name: False for name in CHECK_NAMES}
        try:
            api = inspect()
            result["container"] = api["State"]["Running"] is True
            result["liveness"] = get("/health/live", "live")
            direct_release = get("/version", "release")
            proxy_release = get("/version", "release", proxy=True)
            result["identity"] = api["Image"] == image and direct_release and proxy_release
            result["catalogue"] = get("/items", "items")
            result["proxy"] = get("/items", "items", proxy=True)
            after = inspect()
            stable = (after["Id"] == api["Id"] and after["Image"] == api["Image"]
                      and after.get("RestartCount", 0) == api.get("RestartCount", 0)
                      and after["State"]["Running"] is True)
            result["container"] = result["container"] and stable
        except (InspectionError, KeyError, TypeError, AttributeError, IndexError):
            result["container"] = False
        if all(result.values()) and clock() < deadline:
            return Verification(result, attempts)
        remaining = deadline - clock()
        if remaining > 0:
            sleep(min(settings.retry_interval, remaining))
    # A cycle completing after the deadline is not an accepted success.
    if all(result.values()):
        result["container"] = False
    return Verification(result, attempts)
