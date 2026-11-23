"""Point-in-time connectivity observations for the dedicated catalogue demo."""
from dataclasses import dataclass
from ipaddress import IPv4Address
from pathlib import Path
import sys
import time

from .config import ExitCode, Settings
from .docker import Docker, InspectionError
from .observations import http_label
from .preflight import NETWORK, PROJECT, LABEL, check_resources, containers, require, single
from .processes import CommandError, run_command


TOTAL_SECONDS = 15
PROBE_SECONDS = 3
NETWORK_OUTCOMES = {"ok", "resolution-failed", "unexpected-address", "connection-refused",
                    "resolved-address-unconfirmed", "connection-error", "timeout", "unavailable"}


class DiagnosticDocker(Docker):
    def __init__(self, root, deadline):
        super().__init__(root)
        self.deadline = deadline

    def _run(self, arguments):
        self.timeout = min(PROBE_SECONDS, self.deadline - time.monotonic())
        if self.timeout <= 0:
            raise InspectionError("Diagnostic deadline reached")
        return super()._run(arguments)


@dataclass(frozen=True)
class Service:
    container_id: str
    image: str
    started: str
    state: str
    address: str


@dataclass(frozen=True)
class Observation:
    route: str
    outcome: str
    elapsed_ms: int


def snapshot(docker, root):
    services = check_resources(containers(docker), root, diagnostics=True)
    network = single(docker.json("network", "inspect", NETWORK), "demo network")
    labels = network["Labels"]
    require(network["Name"] == NETWORK and network["Driver"] == "bridge"
            and labels.get(LABEL + "project") == PROJECT and labels.get(LABEL + "network") == "default",
            "Unexpected diagnostic network")
    attached = set(network.get("Containers") or {})
    owned = {item["Id"] for item in services.values()}
    running = {item["Id"] for item in services.values() if item["State"]["Running"]}
    require(running <= attached <= owned, "Unexpected network membership")
    return {
        name: Service(item["Id"], item["Image"], item["State"]["StartedAt"], item["State"]["Status"],
                      item["NetworkSettings"]["Networks"][NETWORK].get("IPAddress") or "")
        for name, item in services.items()
    }


def collect(docker, services, deadline):
    api = services["api"]
    db_ip = services["db"].address if services["db"].state == "running" else ""
    if db_ip:
        db_ip = str(IPv4Address(db_ip))
    probe_source = Path(__file__).with_name("network_probe.py").read_text()
    settings = Settings()
    observations = []
    for name, kind, stopped in (
        ("api -> db (DNS/IPv4)", "dns", api.state != "running"),
        ("api -> db (TCP/5432)", "tcp", api.state != "running"),
        ("host -> api (/items)", "direct", api.state != "running"),
        ("host -> nginx (/items)", "proxy", services["nginx"].state != "running"),
    ):
        start = time.monotonic()
        remaining = min(PROBE_SECONDS, deadline - start)
        if remaining <= 0:
            outcome = "skipped-deadline"
        elif stopped:
            outcome = "skipped-container-exited"
        elif kind == "tcp" and not db_ip:
            outcome = "skipped-no-running-db-address"
        else:
            try:
                if kind in ("dns", "tcp"):
                    value = docker.text("exec", api.container_id, "python", "-I", "-B", "-c",
                                        probe_source, kind, db_ip, str(remaining))
                    outcome = value if value in NETWORK_OUTCOMES else "probe-unavailable"
                else:
                    url = settings.direct_url if kind == "direct" else settings.proxy_url
                    value = run_command([sys.executable, "-I", str(Path(__file__).with_name("http_probe.py")),
                                         url + "/items", "items", "", str(remaining), "--observation"],
                                        docker.root, None, remaining).strip()
                    outcome = http_label(value)
            except (CommandError, InspectionError):
                outcome = "probe-unavailable"
        observations.append(Observation(name, outcome, round((time.monotonic() - start) * 1000)))
    return observations


def diagnose():
    root = Path.cwd().resolve()
    deadline = time.monotonic() + TOTAL_SECONDS
    try:
        docker = DiagnosticDocker(root, deadline)
        docker.connect()
        before = snapshot(docker, root)
        results = collect(docker, before, deadline)
        for row in results:
            print(f"{row.route}: {row.outcome} ({row.elapsed_ms} ms)")
        require(snapshot(docker, root) == before, "Stack changed during diagnostics")
        require(time.monotonic() < deadline, "Diagnostic deadline reached")
    except (InspectionError, OSError, ValueError, KeyError, TypeError, IndexError, AttributeError):
        print("DIAGNOSTICS INCOMPLETE: could not confirm the owned stack within the budget.", file=sys.stderr)
        return ExitCode.PREFLIGHT_REFUSED
    except KeyboardInterrupt:
        return ExitCode.INTERRUPTED
    return ExitCode.OK if all(row.outcome == "ok" for row in results) else ExitCode.DEPLOYMENT_FAILED
