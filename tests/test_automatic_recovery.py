from copy import deepcopy
from unittest.mock import patch

from test_recovery import IMAGE, OTHER, PASS, RecoveryFixture, SECRET
from toolkit.checks import Verification
from toolkit.cli import main
from toolkit.config import DeploymentRequest, ExitCode
from toolkit.deploy import deploy
from toolkit.docker import InspectionError
from toolkit.locking import LockBusy
from toolkit.override import read_override
from toolkit.processes import CommandError
from toolkit.recovery import history, inspect_target
from toolkit.state import CHECK_NAMES, OperationJournal, RecordError, StateUncertain, operation_session, read_state

FAIL = Verification(dict.fromkeys(CHECK_NAMES, False), 1)


class AutomaticRecoveryTests(RecoveryFixture):
    def setUp(self):
        super().setUp()
        self.candidate = DeploymentRequest(OTHER, "demo-v2", self.request.settings)
        self.images = {
            IMAGE: self.docker.image,
            OTHER: dict(deepcopy(self.docker.image), Id=OTHER),
        }
        original = self.docker.json

        def inspect(*args):
            if args[:2] == ("image", "inspect") and args[2].startswith("sha256:"):
                if args[2] not in self.images:
                    raise InspectionError("Local image unavailable")
                return [self.images[args[2]]]
            return original(*args)

        self.docker.json = inspect
        self.replacements = []

    def execute(self, args, *unused):
        record = read_state(self.root)["latest"]
        self.assertEqual(record["status"], "pending")
        image = record["image_id"]
        self.assertEqual(read_override(self.root), image)
        self.assertEqual(args[-8:], ["up", "-d", "--no-deps", "--no-build", "--pull", "never",
                                     "--force-recreate", "api"])
        self.replacements.append(image)
        self.replace_api(image, running=image == IMAGE)

    def candidate_fails(self, request, *args, **kwargs):
        return PASS if request.image == IMAGE else FAIL

    def configure_failed_candidate(self):
        target = self.baseline()
        self.run.side_effect = self.execute
        self.verify.side_effect = self.candidate_fails
        return target

    def automatic(self):
        return deploy(self.candidate, self.root, auto_recover=True)

    def test_failed_candidate_recovers_once_under_lock_and_preserves_trigger(self):
        target = self.configure_failed_candidate()

        def checked_execute(*args):
            with self.assertRaises(LockBusy), operation_session(self.root, allow_pending=True):
                self.fail("Recovery lost the original mutation lock")
            if self.replacements:
                active = read_state(self.root)["latest"]
                trigger = history(self.root, allow_pending=True)[active["recovery"]["trigger"]]
                self.assertEqual(trigger["status"], "failed")
                self.assertEqual(trigger["auto_target"], target)
            return self.execute(*args)

        self.run.side_effect = checked_execute
        self.assertEqual(self.automatic(), ExitCode.DEPLOYMENT_FAILED, self.out.getvalue())
        state = read_state(self.root)
        self.assertEqual(state["version"], 4)
        self.assertEqual(state["latest"], state["last_success"])
        final = state["latest"]
        self.assertEqual((final["status"], final["image_id"]), ("succeeded", IMAGE))
        self.assertEqual(self.replacements, [OTHER, IMAGE])
        self.assertEqual(final["recovery"]["target"], target)
        self.assertEqual(final["recovery"]["kind"], "automatic")
        self.assertIs(final["recovery"]["requested"], False)
        self.assertIs(final["recovery"]["needed"], False)
        trigger_id = final["recovery"]["trigger"]
        self.assertEqual(history(self.root)[trigger_id]["status"], "failed")
        inspect_target(self.root, self.docker, final, False)
        self.assertIn("AUTOMATIC RECOVERY: succeeded", self.out.getvalue())
        self.assertNotIn(SECRET, self.out.getvalue())
        self.assertNotIn(SECRET, (self.directory / "state.json").read_text())

    def test_default_failed_deploy_does_not_recover(self):
        target = self.configure_failed_candidate()
        self.assertEqual(deploy(self.candidate, self.root), ExitCode.DEPLOYMENT_FAILED)
        self.assertEqual(self.replacements, [OTHER])
        state = read_state(self.root)
        self.assertEqual(state["latest"]["status"], "failed")
        self.assertEqual(state["last_success"]["id"], target)
        self.assertNotIn("auto_target", state["latest"])

    def test_successful_opt_in_candidate_becomes_an_eligible_baseline(self):
        target = self.baseline()

        def running_candidate(*args):
            self.execute(*args)
            self.api["State"].update(Status="running", Running=True)
            self.docker.network["Containers"][self.api["Id"]] = {}

        self.run.side_effect = running_candidate
        self.assertEqual(self.automatic(), ExitCode.OK, self.out.getvalue())
        record = read_state(self.root)["latest"]
        self.assertEqual(record["image_id"], OTHER)
        self.assertEqual(record["auto_target"], target)
        self.assertNotIn("recovery", record)
        inspect_target(self.root, self.docker, record, False)
        self.assertEqual(self.replacements, [OTHER])

    def test_no_suitable_last_success_refuses_without_falling_back(self):
        self.assertEqual(self.automatic(), ExitCode.PREFLIGHT_REFUSED)
        target = self.baseline()
        self.assertEqual(deploy(self.request, self.root), ExitCode.OK)
        self.assertEqual(self.automatic(), ExitCode.PREFLIGHT_REFUSED)
        self.assertEqual(history(self.root)[target]["status"], "succeeded")
        self.run.assert_not_called()
        self.assertIn("Register the running API", self.out.getvalue())

    def test_already_running_image_requires_ordinary_verification(self):
        self.baseline()
        self.assertEqual(deploy(self.request, self.root, auto_recover=True), ExitCode.PREFLIGHT_REFUSED)
        self.run.assert_not_called()

    def test_baseline_must_still_be_healthy_before_candidate_runs(self):
        target = self.baseline()
        self.verify.return_value = FAIL
        self.assertEqual(self.automatic(), ExitCode.PREFLIGHT_REFUSED)
        self.assertEqual(read_state(self.root)["latest"]["id"], target)
        self.run.assert_not_called()

    def test_comment_only_is_refused_in_automatic_mode(self):
        target = self.baseline()
        self.compose.write_bytes(self.compose.read_bytes() + b"\n# equivalent comment\n")
        self.assertEqual(self.automatic(), ExitCode.PREFLIGHT_REFUSED)
        self.assertIn("compose_bytes", self.out.getvalue())
        self.assertEqual(read_state(self.root)["latest"]["id"], target)
        self.run.assert_not_called()

    def test_missing_target_image_after_failed_candidate_skips_recovery(self):
        target = self.configure_failed_candidate()

        def remove_baseline(request, *args, **kwargs):
            if request.image == OTHER:
                self.images.pop(IMAGE)
                return FAIL
            return PASS

        self.verify.side_effect = remove_baseline
        self.assertEqual(self.automatic(), ExitCode.DEPLOYMENT_FAILED)
        self.assertEqual(self.replacements, [OTHER])
        state = read_state(self.root)
        self.assertEqual(state["latest"]["status"], "failed")
        self.assertEqual(state["last_success"]["id"], target)
        self.assertIn("AUTOMATIC RECOVERY SKIPPED", self.out.getvalue())
        self.assertIn("Local image unavailable", self.out.getvalue())

    def test_database_schema_drift_skips_recovery_after_failure(self):
        self.configure_failed_candidate()

        def drift(request, *args, **kwargs):
            if request.image == OTHER:
                self.schema["keys"] = []
                return FAIL
            return PASS

        self.verify.side_effect = drift
        self.assertEqual(self.automatic(), ExitCode.DEPLOYMENT_FAILED)
        self.assertEqual(self.replacements, [OTHER])
        self.assertIn("Unsupported public.items schema", self.out.getvalue())

    def test_out_of_band_restart_policy_change_skips_recovery(self):
        self.configure_failed_candidate()

        def drift(request, *args, **kwargs):
            if request.image == OTHER:
                self.api["HostConfig"]["RestartPolicy"]["Name"] = "always"
                return FAIL
            return PASS

        self.verify.side_effect = drift
        self.assertEqual(self.automatic(), ExitCode.DEPLOYMENT_FAILED)
        self.assertEqual(self.replacements, [OTHER])
        self.assertIn("Unexpected container restart policy", self.out.getvalue())

    def test_candidate_replacement_must_be_observed_before_rollback(self):
        self.configure_failed_candidate()
        self.run.side_effect = lambda *args: None
        self.assertEqual(self.automatic(), ExitCode.STATE_UNCERTAIN)
        self.assertEqual(read_state(self.root)["latest"]["status"], "pending")
        self.run.assert_called_once()

    def test_recovery_refuses_same_image_when_candidate_container_has_changed(self):
        self.configure_failed_candidate()

        def replace_outside_the_toolkit(request, *args, **kwargs):
            if request.image == OTHER:
                self.replace_api(OTHER, running=False)
                return FAIL
            return PASS

        self.verify.side_effect = replace_outside_the_toolkit
        self.assertEqual(self.automatic(), ExitCode.DEPLOYMENT_FAILED)
        self.assertEqual(self.replacements, [OTHER])
        self.assertIn("AUTOMATIC RECOVERY SKIPPED", self.out.getvalue())
        self.assertEqual(read_state(self.root)["latest"]["status"], "failed")

    def test_schema_change_during_installed_plan_refuses_the_recovery_mutation(self):
        self.configure_failed_candidate()

        def render_with_drift(args, *args_after, **kwargs):
            if self.replacements and str(self.directory / "compose-image.json") in args:
                self.schema["keys"] = []
            return self.merge(args, *args_after, **kwargs)

        self.render.side_effect = render_with_drift
        self.assertEqual(self.automatic(), ExitCode.STATE_UNCERTAIN)
        self.assertEqual(self.replacements, [OTHER])
        latest = read_state(self.root)["latest"]
        self.assertEqual(latest["status"], "pending")
        self.assertEqual(latest["recovery"]["kind"], "automatic")
        self.assertIn("Unsupported public.items schema", self.out.getvalue())

    def test_unconfirmed_first_command_retains_pending_instead_of_rolling_back(self):
        target = self.configure_failed_candidate()
        self.run.side_effect = CommandError("simulated timeout")
        self.assertEqual(self.automatic(), ExitCode.STATE_UNCERTAIN)
        state = read_state(self.root)
        self.assertEqual(state["latest"]["status"], "pending")
        self.assertEqual(state["last_success"]["id"], target)
        self.run.assert_called_once()

    def test_failed_recovery_is_recorded_without_another_attempt(self):
        target = self.configure_failed_candidate()
        self.verify.side_effect = [PASS, FAIL, FAIL]
        self.assertEqual(self.automatic(), ExitCode.DEPLOYMENT_FAILED)
        final = read_state(self.root)
        self.assertEqual(self.replacements, [OTHER, IMAGE])
        self.assertEqual(final["latest"]["status"], "failed")
        self.assertEqual(final["latest"]["recovery"]["kind"], "automatic")
        self.assertEqual(final["last_success"]["id"], target)
        with operation_session(self.root) as journal:
            with self.assertRaises(StateUncertain):
                journal.begin(IMAGE, "demo-v1", action="replace", recovery=final["latest"]["recovery"])
        self.assertEqual(read_state(self.root), final)

    def test_unconfirmed_recovery_retains_its_pending_record_and_failed_trigger(self):
        self.configure_failed_candidate()

        def time_out(*args):
            if self.replacements:
                raise CommandError("simulated timeout")
            return self.execute(*args)

        self.run.side_effect = time_out
        self.assertEqual(self.automatic(), ExitCode.STATE_UNCERTAIN)
        latest = read_state(self.root)["latest"]
        self.assertEqual(latest["status"], "pending")
        self.assertEqual(history(self.root, allow_pending=True)[latest["recovery"]["trigger"]]["status"], "failed")
        self.assertEqual(self.run.call_count, 2)

    def test_cannot_start_automatic_recovery_until_failure_record_is_durable(self):
        self.configure_failed_candidate()
        with patch.object(OperationJournal, "finish", side_effect=RecordError):
            self.assertEqual(self.automatic(), ExitCode.RECORD_FAILED)
        self.assertEqual(self.replacements, [OTHER])
        self.assertEqual(read_state(self.root)["latest"]["status"], "pending")

    def test_recording_failure_after_recovery_never_returns_a_health_result(self):
        self.configure_failed_candidate()
        finish = OperationJournal.finish

        def fail_final(journal, *args, **kwargs):
            if len(self.replacements) == 2:
                raise RecordError
            return finish(journal, *args, **kwargs)

        with patch.object(OperationJournal, "finish", new=fail_final):
            self.assertEqual(self.automatic(), ExitCode.RECORD_FAILED)
        latest = read_state(self.root)["latest"]
        self.assertEqual(latest["status"], "pending")
        self.assertEqual(latest["recovery"]["kind"], "automatic")
        self.assertNotIn("AUTOMATIC RECOVERY: succeeded", self.out.getvalue())

    def test_lost_trigger_archive_is_refused_when_selecting_another_target(self):
        target = self.configure_failed_candidate()
        self.assertEqual(self.automatic(), ExitCode.DEPLOYMENT_FAILED)
        trigger = read_state(self.root)["latest"]["recovery"]["trigger"]
        (self.directory / f"operation-{trigger}.json").unlink()
        self.assertEqual(main(["rollback", "--to", target, "--dry-run"]), ExitCode.STATE_UNCERTAIN)
        self.assertEqual(self.replacements, [OTHER, IMAGE])

    def test_same_container_restarted_during_candidate_verification_skips_recovery(self):
        self.configure_failed_candidate()
        self.api["State"]["StartedAt"] = "2026-11-22T10:00:00Z"

        def restart_during_verification(request, *args, **kwargs):
            if request.image == OTHER:
                self.api["State"]["StartedAt"] = "2026-11-22T10:00:30Z"
                return FAIL
            return PASS

        self.verify.side_effect = restart_during_verification
        self.assertEqual(self.automatic(), ExitCode.DEPLOYMENT_FAILED)
        self.assertEqual(self.replacements, [OTHER])
        self.assertIn("AUTOMATIC RECOVERY SKIPPED", self.out.getvalue())

    def test_cli_requires_the_flag_and_schema_together(self):
        args = ["deploy", "--image", OTHER, "--release", "demo-v2"]
        for incomplete in (["--auto-recover"], ["--schema", "catalogue-v1"]):
            with self.subTest(incomplete=incomplete), self.assertRaises(SystemExit) as error:
                main(args + incomplete)
            self.assertEqual(error.exception.code, 2)
        with patch("toolkit.cli.deploy", return_value=1) as action:
            self.assertEqual(main(args + ["--auto-recover", "--schema", "catalogue-v1"]), 1)
            self.assertIs(action.call_args.kwargs["auto_recover"], True)
