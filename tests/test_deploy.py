from contextlib import redirect_stdout, redirect_stderr
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from toolkit.checks import Verification
from toolkit.config import DeploymentRequest, Settings
from toolkit.deploy import deploy, replacement_arguments
from toolkit.docker import InspectionError
from toolkit.locking import LockBusy
from toolkit.processes import CommandError
from toolkit.state import CHECK_NAMES, RecordError, operation_session, read_state

IMAGE = "sha256:" + "a" * 64
OLD = "sha256:" + "b" * 64


class DeployTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / 'demo/nginx').mkdir(parents=True)
        for name in ('compose.yaml', '.env', 'demo/nginx/default.conf'):
            (self.root / name).write_text('fixture')
        self.request = DeploymentRequest('demo:v1', 'demo-v1', Settings())
        self.snapshot = dict(candidate_image_id=IMAGE, current_image_id=OLD,
                             expected_release='demo-v1', api_running=True,
                             api_id='1'*64, dependency_ids={'db': '2'*64, 'nginx': '3'*64})
        self.passed = Verification(dict.fromkeys(CHECK_NAMES, True), 1)
        self.failed = Verification(dict.fromkeys(CHECK_NAMES, False), 1)
        self.docker = MagicMock()
        self.docker.environment = {}
        self.docker.json.return_value = [{"Config": {"User": "10001:10001"}}]
        targets = {
            'Docker': {'return_value': self.docker},
            'inspect_preflight': {'side_effect': lambda *a: dict(self.snapshot)},
            'validate_replacement_config': {},
            'run_command': {'return_value': ''},
            'verify': {'return_value': self.passed},
        }
        self.mocks = {}
        for name, arguments in targets.items():
            mock = patch('toolkit.deploy.' + name, **arguments)
            self.mocks[name] = mock.start()
            self.addCleanup(mock.stop)

    def run_deploy(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            result = deploy(self.request, self.root)
        self.output = out.getvalue() + err.getvalue()
        return result

    def test_success_replaces_only_api_and_records_identity_and_checks(self):
        def command(*args):
            current = read_state(self.root)
            self.assertEqual(current['latest']['status'], 'pending')
            self.assertEqual(current['latest']['image_id'], IMAGE)
            with self.assertRaises(LockBusy):
                with operation_session(self.root):
                    self.fail('Second session must be refused')
            return ''
        self.mocks['run_command'].side_effect = command
        self.assertEqual(self.run_deploy(), 0)
        record = read_state(self.root)['latest']
        self.assertEqual(record['action'], 'replace')
        self.assertEqual(record['status'], 'succeeded')
        self.assertEqual(record['checks'], self.passed.checks)
        args = self.mocks['run_command'].call_args.args[0]
        self.assertEqual(args, replacement_arguments(self.root))
        self.assertEqual(args[-8:], ['up', '-d', '--no-deps', '--no-build', '--pull', 'never', '--force-recreate', 'api'])

    def test_matching_running_image_is_verified_without_replacement(self):
        self.snapshot['current_image_id'] = IMAGE
        self.assertEqual(self.run_deploy(), 0)
        self.mocks['run_command'].assert_not_called()
        self.mocks['verify'].assert_called_once()
        self.assertEqual(read_state(self.root)['latest']['action'], 'verify-only')
        self.assertFalse((self.root / '.runtime/toolkit/compose-image.json').exists())

    def test_matching_stopped_image_still_replaces(self):
        self.snapshot.update(current_image_id=IMAGE, api_running=False)
        self.assertEqual(self.run_deploy(), 0)
        self.mocks['run_command'].assert_called_once()
        self.assertEqual(read_state(self.root)['latest']['action'], 'replace')

    def test_verification_failure_preserves_previous_success(self):
        self.assertEqual(self.run_deploy(), 0)
        old_success = read_state(self.root)['last_success']
        self.mocks['verify'].return_value = self.failed
        self.assertEqual(self.run_deploy(), 1)
        self.assertEqual(read_state(self.root)['last_success'], old_success)
        self.assertEqual(read_state(self.root)['latest']['status'], 'failed')

    def test_first_failure_has_no_recovery_target(self):
        self.mocks['verify'].return_value = self.failed
        self.assertEqual(self.run_deploy(), 1)
        self.assertIsNone(read_state(self.root)['last_success'])

    def test_command_error_observes_but_keeps_pending_even_if_checks_pass(self):
        self.mocks['run_command'].side_effect = CommandError('timed out')
        self.assertEqual(self.run_deploy(), 6)
        self.assertEqual(read_state(self.root)['latest']['status'], 'pending')
        self.assertIsNone(read_state(self.root)['last_success'])
        self.assertEqual(self.mocks['verify'].call_args.kwargs['duration'], 10)
        self.assertEqual(self.mocks['run_command'].call_count, 1)
        self.assertIn('OBSERVATION ONLY', self.output)

    def test_pending_state_blocks_before_docker_preflight(self):
        with operation_session(self.root) as journal:
            journal.begin(IMAGE, 'demo-v1')
        self.assertEqual(self.run_deploy(), 6)
        self.mocks['inspect_preflight'].assert_not_called()
        self.mocks['run_command'].assert_not_called()

    def test_contention_returns_five(self):
        with operation_session(self.root):
            self.assertEqual(self.run_deploy(), 5)
        self.mocks['run_command'].assert_not_called()

    def test_preflight_refusal_does_not_begin_operation(self):
        self.mocks['inspect_preflight'].side_effect = InspectionError('foreign resources')
        self.assertEqual(self.run_deploy(), 4)
        self.assertIsNone(read_state(self.root)['latest'])
        self.mocks['run_command'].assert_not_called()

    def test_changed_second_snapshot_is_refused(self):
        second = dict(self.snapshot, api_id='f'*64)
        self.mocks['inspect_preflight'].side_effect = [self.snapshot, second]
        self.assertEqual(self.run_deploy(), 4)
        self.mocks['run_command'].assert_not_called()

    def test_second_preflight_uses_immutable_id(self):
        self.assertEqual(self.run_deploy(), 0)
        self.assertEqual(self.mocks['inspect_preflight'].call_args_list[1].args[0].image, IMAGE)

    def test_configuration_change_before_begin_is_refused(self):
        def alter(*args):
            (self.root / '.env').write_text('changed-secret')
        self.mocks['validate_replacement_config'].side_effect = alter
        self.assertEqual(self.run_deploy(), 4)
        self.assertNotIn('changed-secret', self.output)
        self.mocks['run_command'].assert_not_called()

    def test_configuration_change_after_command_leaves_pending(self):
        def alter(*args):
            (self.root / '.env').write_text('changed-secret')
            return ''
        self.mocks['run_command'].side_effect = alter
        self.assertEqual(self.run_deploy(), 6)
        self.assertEqual(read_state(self.root)['latest']['status'], 'pending')
        self.assertNotIn('changed-secret', self.output)

    def test_initial_record_failure_prevents_replacement(self):
        with patch('toolkit.state.OperationJournal.begin', side_effect=RecordError):
            self.assertEqual(self.run_deploy(), 7)
        self.mocks['run_command'].assert_not_called()

    def test_final_record_failure_is_not_success(self):
        with patch('toolkit.state.OperationJournal.finish', side_effect=RecordError):
            self.assertEqual(self.run_deploy(), 7)
        self.assertEqual(read_state(self.root)['latest']['status'], 'pending')
        self.assertNotIn('SUCCESS:', self.output)

    def test_override_record_failure_prevents_command(self):
        with patch('toolkit.deploy.write_override', side_effect=RecordError):
            self.assertEqual(self.run_deploy(), 7)
        self.mocks['run_command'].assert_not_called()

    def test_keyboard_interrupt_preserves_pending(self):
        self.mocks['run_command'].side_effect = KeyboardInterrupt
        self.assertEqual(self.run_deploy(), 130)
        self.assertEqual(read_state(self.root)['latest']['status'], 'pending')

    def test_unexpected_error_never_prints_raw_exception(self):
        self.mocks['run_command'].side_effect = RuntimeError('private-value')
        self.assertEqual(self.run_deploy(), 6)
        self.assertNotIn('private-value', self.output)

    def test_wrong_directory_does_not_create_runtime_state(self):
        (self.root / 'compose.yaml').unlink()
        self.assertEqual(self.run_deploy(), 4)
        self.assertFalse((self.root / '.runtime').exists())

    def test_root_candidate_refused_before_record(self):
        self.docker.json.return_value = [{'Config': {'User': 'root'}}]
        self.assertEqual(self.run_deploy(), 4)
        self.assertIsNone(read_state(self.root)['latest'])
        self.mocks['run_command'].assert_not_called()

    def test_no_health_success_after_timeout_is_recorded(self):
        self.mocks['run_command'].side_effect = CommandError('nonzero exit')
        self.mocks['verify'].return_value = self.failed
        self.assertEqual(self.run_deploy(), 6)
        self.assertIsNone(read_state(self.root)['last_success'])
        self.assertIn('pending', self.output)

    def test_failed_verify_only_does_not_trigger_replacement(self):
        self.snapshot['current_image_id'] = IMAGE
        self.mocks['verify'].return_value = self.failed
        self.assertEqual(self.run_deploy(), 1)
        self.mocks['run_command'].assert_not_called()
        self.assertEqual(read_state(self.root)['latest']['action'], 'verify-only')


class ConfigurationGuardTests(unittest.TestCase):
    def setUp(self):
        self.docker = MagicMock()
        self.api = {
            'image': IMAGE, 'read_only': True, 'cap_drop': ['ALL'],
            'security_opt': ['no-new-privileges:true'],
            'environment': {'DB_HOST': 'db', 'DB_NAME': 'catalogue',
                            'DB_USER': 'catalogue_reader', 'DB_PASSWORD': 'test-only'},
        }
        self.docker.compose.return_value = {'services': {'api': self.api}}

    def check(self):
        from toolkit.deploy import validate_replacement_config
        return validate_replacement_config(self.docker, Path('/tmp'))

    def test_supported_configuration_passes(self):
        self.check()

    def test_null_startup_fields_preserve_image_defaults(self):
        for fields in ({'command': None}, {'entrypoint': None},
                       {'command': None, 'entrypoint': None}):
            with self.subTest(fields=fields):
                self.api.update(fields)
                self.check()
                for name in fields:
                    self.api.pop(name)

    def test_non_null_startup_fields_are_refused(self):
        for key in ('command', 'entrypoint'):
            for value in ('', [], 'unexpected', ['unexpected'], False, 0, {}):
                with self.subTest(key=key, value=value):
                    self.api[key] = value
                    with self.assertRaises(InspectionError):
                        self.check()
                    self.api.pop(key)

    def test_extra_hooks_or_commands_are_refused(self):
        for key in ('command', 'entrypoint', 'post_start', 'pre_stop', 'privileged'):
            self.api[key] = ['unexpected']
            with self.assertRaises(InspectionError):
                self.check()
            self.api.pop(key)

    def test_hardening_change_refused(self):
        self.api['read_only'] = False
        with self.assertRaises(InspectionError):
            self.check()

    def test_unexpected_database_target_refused(self):
        self.api['environment']['DB_HOST'] = 'foreign'
        with self.assertRaises(InspectionError):
            self.check()
