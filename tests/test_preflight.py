import copy
from pathlib import Path
import tempfile
import unittest

from toolkit.config import DeploymentRequest, Settings
from toolkit.docker import InspectionError
from toolkit.preflight import inspect_preflight, inspect_status, LABEL, NETWORK, VOLUME


class FakeDocker:
    def __init__(self, root):
        self.calls = []
        self.info = {"OSType": "linux", "Architecture": "x86_64"}
        self.image = {"Id": "sha256:" + "a" * 64, "Os": "linux", "Architecture": "amd64", "Config": {}}
        self.config = {
            "name": "sdt-demo",
            "networks": {"default": {"name": NETWORK}},
            "volumes": {"catalogue_data": {"name": VOLUME}},
            "services": {name: {"networks": {"default": None}, "image": name + ":v1"}
                         for name in ("api", "db", "nginx", "init")},
        }
        self.items = []
        for i, name in enumerate(("api", "db", "nginx"), 1):
            port = {} if name == "db" else {
                "8000/tcp" if name == "api" else "80/tcp": [
                    {"HostIp": "127.0.0.1", "HostPort": "8089" if name == "api" else "8088"}
                ]
            }
            if name != "db":
                self.config["services"][name]["ports"] = [{"host_ip": "127.0.0.1", "target": 8000 if name == "api" else 80,
                    "published": "8089" if name == "api" else "8088", "protocol": "tcp"}]
            self.items.append({
                "Id": str(i) * 64, "Name": "/sdt-demo-" + name + "-1", "Image": self.image["Id"],
                "Config": {"Labels": {LABEL + "project": "sdt-demo", LABEL + "service": name,
                    LABEL + "container-number": "1", LABEL + "oneoff": "False",
                    LABEL + "project.working_dir": str(root), LABEL + "project.config_files": str(root / "compose.yaml")}},
                "State": {"Running": True, "Status": "running", "Health": {"Status": "healthy"}},
                "HostConfig": {"PortBindings": port}, "NetworkSettings": {"Networks": {NETWORK: {}}}, "Mounts": [],
            })
        self.items[1]["Mounts"] = [{"Type": "volume", "Name": VOLUME, "Destination": "/var/lib/postgresql"}]
        self.items[2]["Mounts"] = [{"Type": "bind", "Source": str(root / "demo/nginx/default.conf"),
                                  "Destination": "/etc/nginx/conf.d/default.conf", "RW": False}]
        self.config["services"]["db"]["volumes"] = [{"type": "volume", "source": "catalogue_data", "target": "/var/lib/postgresql"}]
        self.config["services"]["nginx"]["volumes"] = [{"type": "bind", "source": str(root / "demo/nginx/default.conf"),
            "target": "/etc/nginx/conf.d/default.conf", "read_only": True}]
        self.volume = {"Name": VOLUME, "Driver": "local", "Labels": {LABEL + "project": "sdt-demo", LABEL + "volume": "catalogue_data"}}
        self.network = {"Name": NETWORK, "Driver": "bridge", "Labels": {LABEL + "project": "sdt-demo", LABEL + "network": "default"},
                        "Containers": {item["Id"]: {} for item in self.items}}
        self.volume_users = [self.items[1]["Id"]]

    def connect(self):
        return self.info

    def compose(self, *args):
        self.calls.append(("compose", *args))
        return self.config

    def text(self, *args):
        self.calls.append(args)
        if args[:2] == ("container", "ls"):
            values = self.volume_users if args[-1].startswith("volume=") else [item["Id"] for item in self.items]
            return "\n".join(values)
        raise AssertionError(args)

    def json(self, *args):
        self.calls.append(args)
        if args[:2] == ("container", "inspect"):
            return self.items
        if args[:2] == ("image", "inspect"):
            return [self.image]
        if args[:2] == ("volume", "inspect"):
            return [self.volume]
        if args[:2] == ("network", "inspect"):
            return [self.network]
        raise AssertionError(args)


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "compose.yaml").write_text("fixture")
        (self.root / ".env").write_text("fixture")
        self.docker = FakeDocker(self.root)
        self.request = DeploymentRequest("demo:v1", "demo-v1", Settings())

    def run_check(self):
        return inspect_preflight(self.request, self.root, self.docker)

    def refused(self):
        with self.assertRaises(InspectionError):
            self.run_check()

    def test_healthy_fixture_resolves_id_using_only_read_commands(self):
        result = self.run_check()
        self.assertEqual(result["candidate_image_id"], "sha256:" + "a" * 64)
        for call in self.docker.calls:
            self.assertIn(call[:2], (("compose", "config"), ("container", "ls"), ("container", "inspect"),
                                    ("image", "inspect"), ("volume", "inspect"), ("network", "inspect")))

    def test_missing_project_file(self):
        (self.root / "compose.yaml").unlink()
        self.refused()

    def test_missing_image(self):
        original = self.docker.json
        def query(*args):
            if args[:2] == ("image", "inspect"):
                raise InspectionError("Image unavailable")
            return original(*args)
        self.docker.json = query
        self.refused()

    def test_wrong_image_platform_or_declared_volumes(self):
        original = copy.deepcopy(self.docker.image)
        for field, value in (("Architecture", "arm64"), ("Os", "windows"), ("Config", {"Volumes": {"/data": {}}}), ("Id", "short")):
            self.docker.image = copy.deepcopy(original)
            self.docker.image[field] = value
            self.refused()

    def test_wrong_checkout_labels(self):
        self.docker.items[0]["Config"]["Labels"][LABEL + "project.working_dir"] = "/another/checkout"
        self.refused()

    def test_duplicate_service(self):
        self.docker.items[1]["Config"]["Labels"][LABEL + "service"] = "api"
        self.refused()

    def test_extra_or_missing_container(self):
        self.docker.items.pop()
        self.refused()

    def test_inconsistent_running_flag_is_refused(self):
        self.docker.items[0]["State"]["Running"] = False
        self.refused()

    def stop_api(self):
        api = self.docker.items[0]
        api["State"].update(Status="exited", Running=False)
        self.docker.network["Containers"].pop(api["Id"])

    def test_stopped_owned_api_without_active_endpoint_passes(self):
        self.stop_api()
        self.assertIs(self.run_check()["api_running"], False)

    def test_stopped_owned_api_with_retained_endpoint_passes(self):
        self.stop_api()
        self.docker.network["Containers"][self.docker.items[0]["Id"]] = {}
        self.assertIs(self.run_check()["api_running"], False)

    def test_stopped_dependencies_remain_refused(self):
        for index in (1, 2):
            with self.subTest(index=index):
                original = copy.deepcopy(self.docker.items[index]["State"])
                self.docker.items[index]["State"].update(Status="exited", Running=False)
                self.refused()
                self.docker.items[index]["State"] = original

    def test_stopped_api_foreign_checkout_is_refused(self):
        self.stop_api()
        self.docker.items[0]["Config"]["Labels"][LABEL + "project.working_dir"] = "/other"
        self.refused()

    def test_stopped_api_unexpected_mount_is_refused(self):
        self.stop_api()
        self.docker.items[0]["Mounts"] = [{"Destination": "/data"}]
        self.refused()

    def test_stopped_api_foreign_network_endpoint_is_refused(self):
        self.stop_api()
        self.docker.network["Containers"]["f" * 64] = {}
        self.refused()

    def test_missing_running_dependency_endpoint_is_refused(self):
        self.stop_api()
        self.docker.network["Containers"].pop(self.docker.items[1]["Id"])
        self.refused()

    def test_paused_restarting_dead_and_created_api_refused(self):
        for state in (
            {"Status": "paused", "Running": True, "Paused": True},
            {"Status": "restarting", "Running": True, "Restarting": True},
            {"Status": "dead", "Running": False, "Dead": True},
            {"Status": "created", "Running": False},
        ):
            with self.subTest(state=state):
                self.docker.items[0]["State"] = state
                self.refused()

    def test_unhealthy_database(self):
        self.docker.items[1]["State"]["Health"]["Status"] = "unhealthy"
        self.refused()

    def test_actual_public_port(self):
        self.docker.items[0]["HostConfig"]["PortBindings"]["8000/tcp"][0]["HostIp"] = "0.0.0.0"
        self.refused()

    def test_unexpected_actual_mount(self):
        self.docker.items[0]["Mounts"] = [{"Destination": "/srv"}]
        self.refused()

    def test_compose_public_port_and_external_volume(self):
        self.docker.config["services"]["api"]["ports"][0]["host_ip"] = "0.0.0.0"
        self.refused()
        self.docker.config["services"]["api"]["ports"][0]["host_ip"] = "127.0.0.1"
        self.docker.config["volumes"]["catalogue_data"]["external"] = True
        self.refused()

    def test_foreign_network_endpoint(self):
        self.docker.network["Containers"]["f" * 64] = {}
        self.refused()

    def test_foreign_volume_user(self):
        self.docker.volume_users.append("f" * 64)
        self.refused()

    def test_wrong_volume_ownership(self):
        self.docker.volume["Labels"][LABEL + "project"] = "other"
        self.refused()

    def test_dependency_image_drift(self):
        self.docker.items[1]["Image"] = "sha256:" + "b" * 64
        self.refused()

    def test_malformed_metadata(self):
        del self.docker.items[0]["HostConfig"]
        self.refused()

    def test_status_can_observe_stopped_containers_without_compose(self):
        (self.root / ".env").unlink()
        self.docker.items[0]["State"]["Status"] = "exited"
        rows = inspect_status(self.root, self.docker)
        self.assertEqual(rows[0]["state"], "exited")
        self.assertFalse(any(call[0] == "compose" for call in self.docker.calls))

    def test_status_no_containers_is_not_health_success(self):
        self.docker.items = []
        self.assertEqual(inspect_status(self.root, self.docker), [])


if __name__ == "__main__":
    unittest.main()
