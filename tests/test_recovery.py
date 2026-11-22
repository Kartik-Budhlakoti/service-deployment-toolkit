from contextlib import chdir, redirect_stderr, redirect_stdout
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_preflight import FakeDocker
from toolkit import compatibility as compat
from toolkit.cli import main
from toolkit.checks import Verification
from toolkit.config import DeploymentRequest, Settings
from toolkit.deploy import deploy
from toolkit.docker import InspectionError
from toolkit.override import read_override
from toolkit.processes import CommandError
from toolkit.recovery import authenticate, history, read_only
from toolkit.state import CHECK_NAMES, RecordError, operation_session, read_state, state_directory

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "sha256:" + "a" * 64
OTHER = "sha256:" + "b" * 64
SECRET = "synthetic-only-sentinel"
PASS = Verification(dict.fromkeys(CHECK_NAMES, True), 1)
RENDERER_IDENTITY = compat.renderer_identity


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.enterContext(chdir(self.root))
        self.out = io.StringIO()
        self.enterContext(redirect_stdout(self.out))
        self.enterContext(redirect_stderr(self.out))
        (self.root / "demo/nginx").mkdir(parents=True)
        self.compose = self.root / "compose.yaml"
        self.compose.write_bytes((ROOT / "compose.yaml").read_bytes())
        (self.root / ".env").write_text(f"APP_DB_PASSWORD={SECRET}\nPOSTGRES_PASSWORD=db-value\n")
        self.proxy = self.root / "demo/nginx/default.conf"
        self.proxy.write_text("proxy fixture\n")
        self.request = DeploymentRequest(IMAGE, "demo-v1", Settings())
        self.docker = d = FakeDocker(self.root)
        d.timeout = 10
        d.environment = {}
        d.image["Config"]["User"] = "10001:10001"
        self.api = d.items[0]
        for item in d.items:
            item["Config"].update(User="10001:10001", Env=[])
        self.api["Config"]["Env"] = ["DB_HOST=db", "DB_USER=catalogue_reader",
                                     "DB_NAME=catalogue", "DB_PASSWORD=" + SECRET]
        self.api["HostConfig"].update(ReadonlyRootfs=True, CapDrop=["ALL"],
                                      SecurityOpt=["no-new-privileges:true"])
        d.config["services"]["api"].update(read_only=True, cap_drop=["ALL"],
            security_opt=["no-new-privileges:true"],
            environment=dict(DB_HOST="db", DB_USER="catalogue_reader", DB_NAME="catalogue", DB_PASSWORD=SECRET))
        d.volume.update(CreatedAt="2026-01-01", Mountpoint="/mock/volume")
        d.network["Id"] = "9" * 64
        d.items[1]["Mounts"][0]["RW"] = True
        self.schema = deepcopy(compat.SCHEMA)
        self.mounted = self.proxy.read_bytes()
        self.version = "mock-compose"
        self.enterContext(patch("toolkit.compatibility.renderer_identity", side_effect=lambda _: self.version))
        original_json, original_text = d.json, d.text

        def inspect(*args):
            if args[0] == "exec":
                return self.schema
            return original_json(*args)

        def inspect_text(*args):
            if args[0] == "exec":
                return hashlib.sha256(self.mounted).hexdigest() + "  /mock"
            return original_text(*args)

        d.json, d.text = inspect, inspect_text
        for module in ("deploy", "recovery"):
            self.enterContext(patch("toolkit." + module + ".Docker", return_value=d))
        self.verify = self.enterContext(patch("toolkit.deploy.verify", return_value=PASS))
        self.run = self.enterContext(patch("toolkit.deploy.run_command"))
        self.render = self.enterContext(patch("toolkit.compatibility.run_command", side_effect=self.merge))
        self.directory = state_directory(self.root)

    def merge(self, args, root, env, timeout, *, stdin):
        model = deepcopy(self.docker.config)
        image = json.load(stdin)["services"]["api"]["image"]
        if "-" not in args:
            self.assertEqual(image, read_override(root))
        model["services"]["api"]["image"] = image
        return json.dumps(model)

    def baseline(self):
        self.assertEqual(deploy(self.request, self.root, baseline=True), 0, self.out.getvalue())
        self.run.assert_not_called()
        return read_state(self.root)["latest"]["id"]

    def test_baseline_preview_and_list(self):
        op = self.baseline()
        before = {p.name: p.read_bytes() for p in self.directory.iterdir()}
        self.assertEqual(read_only(), 0)
        self.assertEqual(read_only(op), 0)
        self.assertIn(op, self.out.getvalue())
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.directory.iterdir()})
        for name, data in before.items():
            if name != "recovery.key":
                self.assertNotIn(SECRET.encode(), data)
        self.assertNotIn(SECRET, self.out.getvalue())

    def test_empty_preview_does_not_create_files(self):
        self.assertEqual(read_only("1" * 32), 4)
        self.assertEqual(read_only(), 0)
        self.assertFalse(self.directory.exists())

    def test_comment_only_waives_one_check_and_records_flags(self):
        op = self.baseline()
        self.compose.write_bytes(self.compose.read_bytes() + b"\n# test\n")
        self.assertEqual(read_only(op), 4)
        self.assertEqual(read_only(op, True), 0)
        self.assertEqual(deploy(root=self.root, target=op, allow=True), 0)
        latest = read_state(self.root)["latest"]
        self.assertEqual(latest["recovery"], dict(kind="rollback", target=op, requested=True, needed=True))
        self.assertNotEqual(latest["id"], op)
        self.assertEqual(history(self.root)[op]["status"], "succeeded")

    def test_changed_target_replaces_only_api(self):
        op = self.baseline()
        self.api["Image"] = OTHER
        def replace(args, *unused):
            self.assertEqual(read_state(self.root)["latest"]["status"], "pending")
            self.assertIn("--profile", args)
            self.assertEqual(args[-1], "api")
            self.api["Image"] = IMAGE
        self.run.side_effect = replace
        self.assertEqual(deploy(root=self.root, target=op), 0, self.out.getvalue())
        self.run.assert_called_once()
        self.assertEqual(read_state(self.root)["latest"]["action"], "replace")

    def test_refusal_after_good_preview(self):
        op = self.baseline()
        self.assertEqual(read_only(op, True), 0)
        self.docker.config["services"]["api"]["environment"]["DB_PASSWORD"] = "changed"
        self.assertEqual(deploy(root=self.root, target=op, allow=True), 4)
        self.run.assert_not_called()
        self.assertEqual(read_state(self.root)["latest"]["id"], op)

    def test_independent_drift_refuses_both_modes(self):
        op = self.baseline()
        def changed():
            self.assertEqual(read_only(op), 4, self.out.getvalue())
            self.assertEqual(read_only(op, True), 4, self.out.getvalue())
        self.version = "new-renderer"
        changed()
        self.version = "mock-compose"
        self.schema["keys"] = []
        changed()
        self.schema = deepcopy(compat.SCHEMA)
        self.docker.volume["CreatedAt"] += "z"
        changed()
        self.docker.volume["CreatedAt"] = "2026-01-01"
        self.mounted += b"mismatch"
        changed()
        self.proxy.write_bytes(self.mounted)
        changed()
        self.proxy.write_bytes(b"proxy fixture\n")
        self.mounted = self.proxy.read_bytes()
        self.docker.config["services"]["init"]["extra"] = True
        changed()
        del self.docker.config["services"]["init"]["extra"]
        with (self.root / ".env").open("a") as file:
            file.write("# changed\n")
        changed()

    def test_source_include_or_port_change_refused_before_render(self):
        original = self.compose.read_bytes()
        for source in (original+b"include: [more.yaml]\n", original.replace(b"8088", b"8087")):
            self.compose.write_bytes(source)
            self.assertEqual(deploy(self.request, self.root, baseline=True), 4)
            self.render.assert_not_called()

    def test_missing_key_and_insecure_key(self):
        op = self.baseline()
        path = self.directory / "recovery.key"
        path.chmod(0o644)
        self.assertEqual(read_only(op, True), 4)
        path.unlink()
        self.assertEqual(read_only(op), 4)
        self.assertEqual(deploy(self.request, self.root, baseline=True), 4)
        self.assertFalse(path.exists())

    def test_modified_key_and_swapped_signature(self):
        op = self.baseline()
        record = history(self.root)[op]
        key = compat.comparison_key(self.root)
        for field, value in (("id", "f"*32), ("release", "other"), ("image_id", OTHER)):
            with self.assertRaises(InspectionError):
                authenticate(dict(record, **{field: value}), key)
        (self.directory / "recovery.key").write_bytes(os.urandom(32))
        self.assertEqual(read_only(op, True), 4)

    def test_corrupt_archive_blocks_selection(self):
        op = self.baseline()
        record = history(self.root)[op]
        (self.directory / f"operation-{op}.json").write_text(json.dumps(dict(record, release="other")))
        self.assertEqual(read_only(op), 6)

    def test_legacy_and_pending_refused(self):
        with operation_session(self.root) as journal:
            op = journal.begin(IMAGE, "v1", action="verify-only")
            journal.finish(op, "succeeded", checks=PASS.checks)
        self.assertEqual(read_only(op), 4)
        with operation_session(self.root) as journal:
            journal.begin(IMAGE, "v2")
        self.assertEqual(read_only(op, True), 6)

    def test_plan_rejects_extra_merged_change(self):
        self.render.side_effect = lambda *args, **kw: json.dumps({"services": {}})
        self.assertEqual(deploy(self.request, self.root, baseline=True), 4)
        self.run.assert_not_called()

    def test_failed_rollback_preserves_previous_success(self):
        op = self.baseline()
        self.verify.return_value = Verification(dict.fromkeys(CHECK_NAMES, False), 1)
        self.assertEqual(deploy(root=self.root, target=op), 1)
        self.assertEqual(read_state(self.root)["last_success"]["id"], op)
        self.assertEqual(read_state(self.root)["latest"]["status"], "failed")

    def test_unconfirmed_replacement_stays_pending(self):
        op = self.baseline()
        self.api["Image"] = OTHER
        self.run.side_effect = CommandError("timeout")
        self.assertEqual(deploy(root=self.root, target=op), 6)
        self.assertEqual(read_state(self.root)["latest"]["status"], "pending")
        self.run.assert_called_once()

    def test_final_write_failure(self):
        op = self.baseline()
        with patch("toolkit.state.OperationJournal.finish", side_effect=RecordError):
            self.assertEqual(deploy(root=self.root, target=op), 7)
        self.assertEqual(read_only(op), 6)

    def test_baseline_cannot_replace_and_evidence_must_be_stable(self):
        self.api["Image"] = OTHER
        self.assertEqual(deploy(self.request, self.root, baseline=True), 4)
        self.api["Image"] = IMAGE
        def drift(*a, **kw):
            self.version = "updated"
            return PASS
        self.verify.side_effect = drift
        self.assertEqual(deploy(self.request, self.root, baseline=True), 6)
        self.assertIsNone(read_state(self.root)["last_success"])
        self.run.assert_not_called()

    def test_no_prefix_or_exception_on_deploy(self):
        for args in (["rollback", "--to", "abcdef"], ["rollback", "--to", "../x"],
                     ["deploy", "--image", IMAGE, "--release", "v1", "--allow-equivalent-config"]):
            with self.assertRaises(SystemExit) as error:
                main(args)
            self.assertEqual(error.exception.code, 2)

    def test_hidden_line_break_in_comment_refused_before_compose(self):
        for newline in (b"\r", b"\xc2\x85", b"\xe2\x80\xa8"):
            self.compose.write_bytes((ROOT / "compose.yaml").read_bytes() + b"# comment" + newline + b"include: [other]\n")
            self.assertEqual(deploy(self.request, self.root, baseline=True), 4)
        self.render.assert_not_called()

    def test_unexpected_runtime_environment_is_refused_without_disclosure(self):
        op = self.baseline()
        self.docker.items[1]["Config"]["Env"].append("EXTRA=" + SECRET)
        self.assertEqual(read_only(op, True), 4)
        self.assertNotIn(SECRET, self.out.getvalue())

    def test_selected_image_and_failed_target_refusals(self):
        op = self.baseline()
        self.docker.image["Id"] = OTHER
        self.assertEqual(read_only(op, True), 4)
        self.docker.image["Id"] = IMAGE
        self.verify.return_value = Verification(dict.fromkeys(CHECK_NAMES, False), 1)
        self.assertEqual(deploy(self.request, self.root, baseline=True), 1)
        failed = read_state(self.root)["latest"]["id"]
        self.assertEqual(read_only(failed, True), 4)
        self.assertEqual(read_only(op), 0)

    def test_effective_plan_from_disk_rechecked_before_up(self):
        op = self.baseline()
        self.api["Image"] = OTHER
        def merge(*args, **kw):
            if "-" not in args[0]:
                return "{}"
            return self.merge(*args, **kw)
        self.render.side_effect = merge
        self.assertEqual(deploy(root=self.root, target=op), 6)
        self.run.assert_not_called()
        self.assertEqual(read_state(self.root)["latest"]["status"], "pending")

    def test_stale_flag_is_not_needed_for_identical_bytes(self):
        op = self.baseline()
        self.assertEqual(deploy(root=self.root, target=op, allow=True), 0)
        self.assertEqual(read_state(self.root)["latest"]["recovery"],
                         dict(kind="rollback", target=op, requested=True, needed=False))

    def test_rollback_does_not_change_a_prior_failed_deployment(self):
        op = self.baseline()
        self.verify.return_value = Verification(dict.fromkeys(CHECK_NAMES, False), 1)
        self.assertEqual(deploy(self.request, self.root), 1)
        failure = read_state(self.root)["latest"]
        self.verify.return_value = PASS
        self.assertEqual(deploy(root=self.root, target=op), 0)
        self.assertEqual(history(self.root)[failure["id"]], failure)
        self.assertEqual(failure["status"], "failed")

    def test_pending_state_blocks_manual_attempt_before_any_mutation(self):
        op = self.baseline()
        with operation_session(self.root) as journal:
            journal.begin(IMAGE, "v1")
        self.assertEqual(deploy(root=self.root, target=op, allow=True), 6)
        self.run.assert_not_called()

    def test_key_symlink_and_archive_id_mismatch_refused(self):
        op = self.baseline()
        key = self.directory / "recovery.key"
        key.rename(self.directory / "moved-key")
        key.symlink_to(self.directory / "moved-key")
        self.assertEqual(read_only(op, True), 4)
        record = history(self.root)[op]
        (self.directory / ("operation-" + "e"*32 + ".json")).write_text(json.dumps(record))
        self.assertEqual(read_only(op), 6)

    def test_renderer_identity_tracks_local_plugin_and_refuses_missing_metadata(self):
        from unittest.mock import MagicMock
        cli = self.root / "docker-cli"
        plugin = self.root / "compose-plugin"
        cli.write_text("cli fixture")
        plugin.write_text("plugin fixture")
        docker = MagicMock()
        docker.environment = {}
        docker.json.return_value = [{"Name": "compose", "Path": str(plugin)}]
        docker.text.return_value = "5.7.1"
        with patch("toolkit.compatibility.shutil.which", return_value=str(cli)):
            first = RENDERER_IDENTITY(docker)
            plugin.write_text("different plugin fixture")
            self.assertNotEqual(first, RENDERER_IDENTITY(docker))
            docker.json.return_value = []
            with self.assertRaises(InspectionError):
                RENDERER_IDENTITY(docker)

    def test_cli_baseline_requires_explicit_contract(self):
        with self.assertRaises(SystemExit) as error:
            main(["baseline", "--image", IMAGE, "--release", "demo-v1"])
        self.assertEqual(error.exception.code, 2)
        self.assertEqual(main(["baseline", "--image", IMAGE, "--release", "demo-v1",
                               "--schema", "catalogue-v1"]), 0)
        self.assertEqual(read_state(self.root)["latest"]["recovery"]["kind"], "baseline")
