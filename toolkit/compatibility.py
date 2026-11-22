"""Observe the supported catalogue configuration. Persist only keyed comparisons."""
from copy import deepcopy
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import stat
import shutil

from .docker import InspectionError, unique_object
from .override import override_path, read_override
from .preflight import NETWORK, VOLUME, check_resources, containers, require, single
from .processes import CommandError, run_command
from .state import _sync_directory, state_directory

CONTRACT = "catalogue-v1"
SOURCE_SHAPE = "a602777f107b20510c31111d7d80a5d1823da7e78ca79eb2042d56383cd592fd"
FIELDS = {"compose_bytes", "model", "environment_file", "proxy_file", "resources", "renderer", "checkout"}
SCHEMA_SQL = """
SELECT json_build_object(
 'kind', c.relkind,
 'columns', (SELECT json_agg(json_build_array(a.attname, format_type(a.atttypid,a.atttypmod),
                      a.attnotnull) ORDER BY a.attnum)
             FROM pg_attribute a WHERE a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped),
 'keys', (SELECT json_agg(pg_get_constraintdef(k.oid)) FROM pg_constraint k
          WHERE k.conrelid=c.oid AND k.contype='p'))
FROM pg_class c WHERE c.oid=to_regclass('public.items')
"""
SCHEMA = {"kind": "r", "columns": [["id", "integer", True], ["name", "text", True]],
          "keys": ["PRIMARY KEY (id)"]}


def regular_bytes(path, private=False):
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    with os.fdopen(os.open(path, flags), "rb") as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode), "Expected a regular recovery input")
        if private:
            require(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o600
                    and info.st_nlink == 1, "Comparison key must be an owner-only regular file")
        data = stream.read(1048577)
        require(len(data) <= 1048576, "Recovery input exceeds the size limit")
        return data


def comparison_key(root, create=False):
    directory = state_directory(root)
    path = directory / "recovery.key"
    try:
        if create:
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            except FileExistsError:
                pass
            else:
                with os.fdopen(fd, "wb") as file:
                    file.write(os.urandom(32))
                    file.flush()
                    os.fsync(file.fileno())
                _sync_directory(directory)
        key = regular_bytes(path, private=True)
        require(len(key) == 32, "Comparison key has an unsupported length")
        return key
    except OSError:
        raise InspectionError("Comparison key is missing or unreadable") from None


def source_lines(data):
    normalized = data.replace(b"\r\n", b"\n")
    require(re.fullmatch(rb"[\x20-\x7e\t\n]*", normalized) is not None,
            "Unsupported encoding or control character in recovery source")
    return normalized.split(b"\n")


def read_inputs(root, docker):
    # Only these literal source lines can reference external input. A resolved
    # model alone would hide whether another file supplied an equivalent value.
    try:
        for name in ("demo", "demo/nginx"):
            require(stat.S_ISDIR((root / name).lstat().st_mode), "Unsupported proxy input path")
        raw = regular_bytes(root / "compose.yaml")
        shape = b"\n".join(line.rstrip() for line in source_lines(raw)
                           if line.strip() and not line.lstrip().startswith(b"#"))
        require(hashlib.sha256(shape).hexdigest() == SOURCE_SHAPE, "Unsupported base Compose source")
        env = regular_bytes(root / ".env")
        keys = []
        for line in source_lines(env):
            if line.strip() and not line.lstrip().startswith(b"#"):
                match = re.fullmatch(rb"(APP_DB_PASSWORD|POSTGRES_PASSWORD)=[A-Za-z0-9._~-]+", line)
                require(match is not None, "Unsupported environment-file syntax")
                keys.append(match[1])
        require(sorted(keys) == [b"APP_DB_PASSWORD", b"POSTGRES_PASSWORD"], "Expected two distinct environment assignments")
        require(all(not k.startswith("COMPOSE_") or k == "COMPOSE_DISABLE_ENV_FILE"
                    for k in docker.environment), "Unsupported Compose environment override")
        return raw, env, regular_bytes(root / "demo/nginx/default.conf")
    except OSError:
        raise InspectionError("A required recovery input is missing or unreadable") from None


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def signed(key, field, value):
    data = value if isinstance(value, bytes) else canonical(value)
    return hmac.digest(key, b"sdt/recovery/v1/" + field.encode() + b"\0" + data, "sha256").hex()


def parse_environment(entries):
    require(isinstance(entries, list), "Container environment is unavailable")
    actual = {}
    for entry in entries:
        name, sep, value = entry.partition("=")
        require(sep and name not in actual, "Ambiguous container environment")
        actual[name] = value
    return actual


def compose_arguments(root, extra_file=None):
    args = ["docker", "--context", "default", "compose", "--project-directory", str(root),
            "--env-file", str(root / ".env"), "-p", "sdt-demo", "-f", str(root / "compose.yaml")]
    if extra_file is not None:
        args.extend(["-f", str(extra_file)])
    return args + ["--profile", "*"]


def check_plan(docker, root, base, image, installed=False):
    overlay = {"services": {"api": {"image": image}}}
    expected = deepcopy(base)
    expected["services"]["api"]["image"] = image
    if installed:
        require(read_override(root) == image, "Stored image override differs")
    filename = override_path(root) if installed else "-"
    args = compose_arguments(root, filename) + ["config", "--format", "json"]
    try:
        with os.fdopen(os.memfd_create("compose-image"), "w+b") as stream:
            stream.write(canonical(overlay))
            stream.seek(0)
            result = run_command(args, root, docker.environment, docker.timeout, stdin=stream)
        actual = json.loads(result, object_pairs_hook=unique_object)
        require(canonical(actual) == canonical(expected), "Merged Compose plan changes more than the API image")
    except (OSError, ValueError, RecursionError, CommandError):
        raise InspectionError("Could not validate the merged Compose plan") from None


def renderer_identity(docker):
    cli = shutil.which("docker", path=docker.environment.get("PATH"))
    require(cli is not None, "Docker CLI path is unavailable")
    plugins = docker.json("info", "--format", "{{json .ClientInfo.Plugins}}")
    compose = [entry for entry in plugins if entry.get("Name") == "compose"]
    require(len(compose) == 1, "Expected one Compose plugin")
    identity = [docker.text("compose", "version", "--short")]
    require(bool(identity[0]), "Missing Compose version")
    for name in (cli, compose[0].get("Path")):
        require(isinstance(name, str) and Path(name).is_absolute(), "Missing local renderer path")
        try:
            path = Path(name).resolve(strict=True)
            info = path.stat()
        except OSError:
            raise InspectionError("Cannot identify the local renderer") from None
        require(stat.S_ISREG(info.st_mode), "Unsupported renderer executable")
        identity.append([str(path), info.st_dev, info.st_ino, info.st_size, info.st_ctime_ns])
    return identity


def observe(root, docker, key, image, *, plan=True):
    raw, env, proxy = read_inputs(root, docker)
    model = docker.compose("config", "--format", "json")
    try:
        if plan:
            check_plan(docker, root, model, image)
        services = model["services"]
        current = check_resources(containers(docker), root)
        for name in ("api", "db", "nginx"):
            item = current[name]
            defaults = single(docker.json("image", "inspect", item["Image"]), "running service image")["Config"]
            expected_env = parse_environment(defaults.get("Env") or [])
            expected_env.update(services[name].get("environment", {}))
            require(parse_environment(item["Config"]["Env"]) == expected_env,
                    "Running service environment differs from Compose and its image")
            for field in ("Cmd", "Entrypoint", "User"):
                require((item["Config"].get(field) or None) == (defaults.get(field) or None),
                        "Running service command or identity differs from its image")
        api = current["api"]
        host = api["HostConfig"]
        require(api["Config"]["User"] == "10001:10001" and host["ReadonlyRootfs"] is True
                and not host.get("CapAdd") and host["CapDrop"] == ["ALL"] and host["SecurityOpt"] in (
                    ["no-new-privileges:true"], ["no-new-privileges=true"]),
                "Running API hardening differs")
        db = current["db"]
        require(db["Mounts"][0]["RW"] is True, "Database mount must be writable")
        actual_proxy = docker.text("exec", current["nginx"]["Id"], "sha256sum", "/etc/nginx/conf.d/default.conf")
        require(actual_proxy.split()[:1] == [hashlib.sha256(proxy).hexdigest()], "Mounted proxy file differs")
        schema = docker.json("exec", "-e", "PGOPTIONS=-c statement_timeout=5000 -c default_transaction_read_only=on",
                             db["Id"], "psql", "-h", "/var/run/postgresql", "-p", "5432", "-XAt", "-v", "ON_ERROR_STOP=1",
                             "-U", "catalogue_admin", "-d", "catalogue", "-c", SCHEMA_SQL)
        require(canonical(schema) == canonical(SCHEMA), "Unsupported public.items schema")
        volume = single(docker.json("volume", "inspect", VOLUME), "volume")
        network = single(docker.json("network", "inspect", NETWORK), "network")
        require(bool(volume.get("CreatedAt")) and bool(volume.get("Mountpoint"))
                and re.fullmatch("[0-9a-f]{64}", network.get("Id", "")), "Missing volume or network identity")
        resources = [network["Id"], volume["Name"], volume["CreatedAt"], volume["Mountpoint"],
                     [[current[n]["Id"], current[n]["Image"]] for n in ("db", "nginx")], schema]
        renderer = renderer_identity(docker)
        values = dict(compose_bytes=raw, model=model, environment_file=env, proxy_file=proxy,
                      resources=resources, renderer=renderer, checkout=[str(root), "sdt-demo"])
        return {name: signed(key, name, value) for name, value in values.items()}
    except (KeyError, TypeError, AttributeError, IndexError, ValueError, RecursionError):
        raise InspectionError("Incomplete or unsupported recovery observation") from None
