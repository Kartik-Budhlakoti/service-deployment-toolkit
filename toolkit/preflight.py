from pathlib import Path
import re

from .docker import Docker, InspectionError
from .override import config_label_allowed, override_path, read_override


PROJECT = "sdt-demo"
NETWORK = "sdt-demo_default"
VOLUME = "sdt-demo_catalogue_data"
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}")
CONTAINER_ID = re.compile(r"[0-9a-f]{64}")
LABEL = "com.docker.compose."


def require(condition, message):
    if not condition:
        raise InspectionError(message)


def single(value, kind):
    require(isinstance(value, list) and len(value) == 1 and isinstance(value[0], dict),
            f"Expected exactly one {kind} inspection result")
    return value[0]


def image_id(image):
    value = image.get("Id", "")
    require(isinstance(value, str) and IMAGE_ID.fullmatch(value), "Image identity is missing or malformed")
    return value


def containers(docker):
    identifiers = docker.text("container", "ls", "--all", "--quiet", "--no-trunc",
                              "--filter", "label=com.docker.compose.project=sdt-demo").split()
    require(len(identifiers) <= 20, "Unexpected number of project containers")
    require(all(CONTAINER_ID.fullmatch(value) for value in identifiers), "Malformed container identifiers")
    if not identifiers:
        return []
    values = docker.json("container", "inspect", *identifiers)
    require(isinstance(values, list) and len(values) == len(identifiers), "Incomplete container inspection")
    require(all(isinstance(value, dict) for value in values), "Malformed container inspection")
    require({value.get("Id") for value in values} == set(identifiers), "Container inspection identities changed")
    return values


def inspect_status(root=None, docker=None):
    docker = docker or Docker(root or Path.cwd())
    docker.connect()
    rows = []
    for item in containers(docker):
        labels = (item.get("Config") or {}).get("Labels") or {}
        service = labels.get(LABEL + "service")
        require(service in ("api", "db", "nginx", "init"), "Unrecognized project service; inspect manually")
        state = (item.get("State") or {}).get("Status")
        require(state in ("created", "running", "paused", "restarting", "removing", "exited", "dead"),
                "Unrecognized container state")
        rows.append({"service": service, "state": state, "image_id": image_id({"Id": item.get("Image")})})
    return sorted(rows, key=lambda row: row["service"])


def check_compose(config, root):
    require(config.get("name") == PROJECT, "Unexpected Compose project name")
    services = config.get("services", {})
    require(set(services) == {"api", "db", "nginx", "init"}, "Compose service set differs from the supported demo")
    require(set(config.get("networks", {})) == {"default"}, "Only the demo default network is supported")
    network = config["networks"]["default"]
    require(network.get("name") == NETWORK and not network.get("external"), "Unexpected Compose network ownership")
    volumes = config.get("volumes", {})
    require(set(volumes) == {"catalogue_data"}, "Unexpected Compose volumes")
    require(volumes["catalogue_data"].get("name") == VOLUME and not volumes["catalogue_data"].get("external"),
            "Unexpected Compose database volume ownership")
    for name, service in services.items():
        require(not any(service.get(key) for key in ("container_name", "network_mode", "privileged", "devices", "volumes_from")),
                f"Unsupported resource settings for {name}")
        require(set(service.get("networks", {})) == {"default"}, f"Unexpected networks for {name}")
    for name, target, published in (("api", 8000, "8089"), ("nginx", 80, "8088")):
        ports = services[name].get("ports", [])
        require(len(ports) == 1, f"Unexpected port count for {name}")
        port = ports[0]
        require(port.get("host_ip") == "127.0.0.1" and port.get("target") == target
                and str(port.get("published")) == published and port.get("protocol", "tcp") == "tcp",
                f"Unexpected loopback port mapping for {name}")
    require(not services["db"].get("ports") and not services["init"].get("ports"), "Database/initializer ports must not be published")
    require(not services["api"].get("volumes") and not services["init"].get("volumes"), "API/initializer mounts are unsupported")
    db_mounts = services["db"].get("volumes", [])
    require(len(db_mounts) == 1 and db_mounts[0].get("type") == "volume"
            and db_mounts[0].get("source") == "catalogue_data"
            and db_mounts[0].get("target") == "/var/lib/postgresql", "Unexpected Compose database mount")
    proxy_mounts = services["nginx"].get("volumes", [])
    require(len(proxy_mounts) == 1 and proxy_mounts[0].get("type") == "bind"
            and proxy_mounts[0].get("source") == str(root / "demo/nginx/default.conf")
            and proxy_mounts[0].get("target") == "/etc/nginx/conf.d/default.conf"
            and proxy_mounts[0].get("read_only") is True, "Unexpected Compose proxy mount")


def check_resources(items, root, *, pending_image=None):
    require(len(items) == 3, "Expected exactly api, db and nginx containers; initialize the demo or resolve extra resources")
    selected = {}
    for item in items:
        labels = item["Config"].get("Labels") or {}
        service = labels.get(LABEL + "service")
        require(service in {"api", "db", "nginx"} and service not in selected, "Duplicate or unexpected project service")
        require(labels.get(LABEL + "project") == PROJECT and labels.get(LABEL + "container-number") == "1"
                and str(labels.get(LABEL + "oneoff")).lower() == "false", "Unexpected Compose container ownership")
        require(labels.get(LABEL + "project.working_dir") == str(root)
                and config_label_allowed(root, service, labels.get(LABEL + "project.config_files")),
                "Container belongs to another checkout or Compose file; automatic adoption refused")
        require(item.get("Name") == f"/{PROJECT}-{service}-1", "Unexpected container name")
        state = item["State"]
        running = state.get("Status") == "running" and state.get("Running") is True
        stopped_api = (service == "api" and state.get("Status") == "exited"
                       and state.get("Running") is False)
        require((running or stopped_api) and not state.get("Paused")
                and not state.get("Restarting") and not state.get("Dead"),
                f"Unsupported container state for {service}")
        if service == "db":
            require(state.get("Health", {}).get("Status") == "healthy", "Database health check is not healthy")
        host = item["HostConfig"]
        require(not host.get("Privileged") and not host.get("Devices"), "Unexpected container host access")
        ports = host.get("PortBindings") or {}
        expected = {} if service == "db" else {
            "8000/tcp" if service == "api" else "80/tcp": [
                {"HostIp": "127.0.0.1", "HostPort": "8089" if service == "api" else "8088"}
            ]
        }
        require(ports == expected, f"Unexpected actual port bindings for {service}")
        require(set(item["NetworkSettings"]["Networks"]) == {NETWORK}, f"Unexpected actual networks for {service}")
        mounts = item.get("Mounts", [])
        if service == "api":
            require(not mounts, "Unexpected API mounts")
        elif service == "db":
            require(len(mounts) == 1 and mounts[0].get("Type") == "volume"
                    and mounts[0].get("Name") == VOLUME and mounts[0].get("Destination") == "/var/lib/postgresql",
                    "Unexpected actual database mount")
        else:
            require(len(mounts) == 1 and mounts[0].get("Type") == "bind"
                    and mounts[0].get("Source") == str(root / "demo/nginx/default.conf")
                    and mounts[0].get("Destination") == "/etc/nginx/conf.d/default.conf"
                    and mounts[0].get("RW") is False, "Unexpected actual proxy mount")
        if service == "api" and labels.get(LABEL + "project.config_files") == (
                str(root / "compose.yaml") + "," + str(override_path(root))):
            override = read_override(root)
            require(item.get("Image") == override or (pending_image is not None and override == pending_image),
                    "API image differs from toolkit override")
        image_id({"Id": item.get("Image")})
        selected[service] = item
    return selected


def inspect_preflight(request, root=None, docker=None, *, pending_image=None):
    root = Path(root or Path.cwd()).resolve()
    docker = docker or Docker(root, request.settings.command_timeout)
    try:
        info = docker.connect()
        require((root / "compose.yaml").is_file() and (root / ".env").is_file(),
                "Run from the project root with compose.yaml and the existing .env")
        config = docker.compose("config", "--format", "json")
        check_compose(config, root)
        candidate = single(docker.json("image", "inspect", request.image), "candidate image")
        resolved = image_id(candidate)
        architecture = {"x86_64": "amd64", "aarch64": "arm64"}.get(info.get("Architecture"), info.get("Architecture"))
        require(candidate.get("Os") == "linux" and candidate.get("Architecture") == architecture,
                "Candidate image platform does not match the local daemon")
        require(not candidate.get("Config", {}).get("Volumes"), "Candidate image declares unsupported volumes")
        selected = check_resources(containers(docker), root, pending_image=pending_image)
        for name in ("db", "nginx"):
            expected_image = single(docker.json("image", "inspect", config["services"][name]["image"]), "dependency image")
            require(selected[name]["Image"] == image_id(expected_image), f"Running {name} image differs from Compose configuration")
        volume = single(docker.json("volume", "inspect", VOLUME), "volume")
        labels = volume.get("Labels") or {}
        require(volume.get("Name") == VOLUME and volume.get("Driver") == "local"
                and not volume.get("Options") and labels.get(LABEL + "project") == PROJECT
                and labels.get(LABEL + "volume") == "catalogue_data", "Database volume ownership/options differ")
        users = docker.text("container", "ls", "--all", "--quiet", "--no-trunc", "--filter", f"volume={VOLUME}").split()
        require(users == [selected["db"]["Id"]], "Database volume is shared with unexpected containers")
        network = single(docker.json("network", "inspect", NETWORK), "network")
        labels = network.get("Labels") or {}
        require(network.get("Name") == NETWORK and network.get("Driver") == "bridge"
                and labels.get(LABEL + "project") == PROJECT and labels.get(LABEL + "network") == "default",
                "Demo network ownership differs")
        owned_ids = {item["Id"] for item in selected.values()}
        required_ids = {item["Id"] for item in selected.values() if item["State"]["Running"]}
        attached_ids = set(network.get("Containers") or {})
        require(required_ids <= attached_ids <= owned_ids,
                "Demo network has missing or unexpected attached containers")
        return {"candidate_image_id": resolved, "current_image_id": selected["api"]["Image"],
                "expected_release": request.release, "api_running": selected["api"]["State"]["Running"],
                "api_id": selected["api"]["Id"],
                "api_started_at": selected["api"]["State"].get("StartedAt"),
                "dependency_ids": {name: selected[name]["Id"] for name in ("db", "nginx")}}
    except (KeyError, TypeError, AttributeError, IndexError):
        raise InspectionError("Docker/Compose metadata has an unsupported or incomplete structure") from None


def validate_replacement_config(docker, root):
    config = docker.compose("config", "--format", "json")
    try:
        api = config["services"]["api"]
        allowed = {"build", "image", "environment", "ports", "networks", "depends_on",
                   "healthcheck", "read_only", "cap_drop", "security_opt",
                   "command", "entrypoint"}
        require(set(api) <= allowed, "Unsupported API deployment configuration")
        require(api.get("command") is None and api.get("entrypoint") is None,
                "API command and entrypoint overrides are unsupported")
        require(api.get("read_only") is True and api.get("cap_drop") == ["ALL"]
                and api.get("security_opt") == ["no-new-privileges:true"],
                "Expected API hardening is missing")
        require(set(api.get("environment", {})) == {"DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD"},
                "Unsupported API environment settings")
        require(api["environment"]["DB_HOST"] == "db"
                and api["environment"]["DB_NAME"] == "catalogue"
                and api["environment"]["DB_USER"] == "catalogue_reader",
                "Unexpected API database configuration")
    except (KeyError, TypeError, AttributeError):
        raise InspectionError("Unsupported API deployment configuration") from None

def require_demo_user(docker, image):
    candidate = single(docker.json("image", "inspect", image), "candidate image")
    require((candidate.get("Config") or {}).get("User") == "10001:10001",
            "Candidate must retain the demo non-root user 10001:10001")
