from dataclasses import dataclass
from pathlib import Path
import sys
import time

from .docker import InspectionError
from .observations import ROUTES, http_label, observed_instance
from .preflight import check_resources, containers
from .processes import CommandError, run_command
from .state import CHECK_NAMES


@dataclass(frozen=True)
class Verification:
    checks: dict
    attempts: int
    trace: dict | None = None

    @property
    def passed(self):
        return all(self.checks.values())


def http_observation(url, kind, release, timeout):
    try:
        result = run_command(
            [sys.executable, "-I", str(Path(__file__).with_name("http_probe.py")),
             url, kind, release, str(timeout), "--observation"],
            Path(__file__).parent, None, timeout,
        )
        return http_label(result.strip())
    except CommandError:
        return "probe-unavailable"


def http_check(url, kind, release, timeout):
    return http_observation(url, kind, release, timeout) == "ok"


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
           clock=time.monotonic, sleep=time.sleep, http=http_observation, *, expected_api=None):
    settings = request.settings
    deadline = clock() + (duration if duration is not None else settings.verification_timeout)
    bounded = BudgetDocker(docker, deadline, clock)
    result = {name: False for name in CHECK_NAMES}
    attempts = 0

    first_failed = last = None

    def get(route, path, kind, proxy=False):
        remaining = deadline - clock()
        if remaining <= 0:
            last["routes"][route] = "deadline"
            return False
        base = settings.proxy_url if proxy else settings.direct_url
        value = http(base + path, kind, request.release, min(settings.request_timeout, remaining))
        label = http_label(value) if value is not True else "ok"
        last["routes"][route] = label
        return label == "ok"

    def inspect():
        selected = check_resources(containers(bounded), root)
        if any(selected[name]["Id"] != value for name, value in dependency_ids.items()):
            raise InspectionError("Dependency container changed during verification")
        api = selected["api"]
        if expected_api is not None and (api["Id"], api["State"].get("StartedAt")) != expected_api:
            raise InspectionError("API instance changed during verification")
        return api

    while clock() < deadline:
        attempts += 1
        result = {name: False for name in CHECK_NAMES}
        last = {"number": attempts, "instance": None, "inspection": "unconfirmed",
                "deadline": False, "routes": dict.fromkeys(ROUTES, "not-run")}
        try:
            api = inspect()
            last["instance"] = observed_instance(api)
            result["container"] = api["State"]["Running"] is True
            result["liveness"] = get("live", "/health/live", "live")
            direct_release = get("direct_version", "/version", "release")
            proxy_release = get("proxy_version", "/version", "release", proxy=True)
            result["identity"] = api["Image"] == image and direct_release and proxy_release
            result["catalogue"] = get("direct_items", "/items", "items")
            result["proxy"] = get("proxy_items", "/items", "items", proxy=True)
            after = inspect()
            stable = (after["Id"] == api["Id"] and after["Image"] == api["Image"]
                      and after.get("RestartCount", 0) == api.get("RestartCount", 0)
                      and after["State"].get("StartedAt") == api["State"].get("StartedAt")
                      and after["State"]["Running"] is api["State"]["Running"])
            if stable:
                last["inspection"] = "running" if result["container"] else "exited"
            else:
                last["inspection"] = "changed"
            result["container"] = result["container"] and stable
        except (InspectionError, KeyError, TypeError, AttributeError, IndexError):
            result["container"] = False
        last["deadline"] = clock() >= deadline
        if all(result.values()) and not last["deadline"]:
            return Verification(result, attempts, {"first_failed": first_failed, "last": last})
        if first_failed is None:
            first_failed = last
        remaining = deadline - clock()
        if remaining > 0:
            sleep(min(settings.retry_interval, remaining))
    # A cycle completing after the deadline is not an accepted success.
    if all(result.values()):
        result["container"] = False
    trace = {"first_failed": first_failed, "last": last} if last else None
    return Verification(result, attempts, trace)
