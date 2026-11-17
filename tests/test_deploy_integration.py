"""Integrate real preflight, journal and verifier using a fake daemon and HTTP."""
from contextlib import redirect_stdout, redirect_stderr
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_preflight import FakeDocker
from toolkit.checks import verify
from toolkit.config import DeploymentRequest, Settings
from toolkit.deploy import deploy
from toolkit.override import override_path
from toolkit.preflight import LABEL
from toolkit.state import read_state


class DeploymentIntegrationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root/'demo/nginx').mkdir(parents=True)
        for name in ('compose.yaml', '.env', 'demo/nginx/default.conf'):
            (self.root/name).write_text('fixture')
        self.docker = FakeDocker(self.root)
        self.docker.timeout = 60
        self.docker.environment = {}
        self.docker.image['Config']['User'] = '10001:10001'
        self.docker.config['services']['api'].update(
            command=None, entrypoint=None,
            read_only=True, cap_drop=['ALL'], security_opt=['no-new-privileges:true'],
            environment=dict(DB_HOST='db', DB_NAME='catalogue', DB_USER='catalogue_reader', DB_PASSWORD='test'))
        self.request = DeploymentRequest('demo:v1','demo-v1',Settings())

    def invoke(self):
        def checks(*args, **kwargs):
            return verify(*args, **kwargs, http=lambda *a: True)
        with patch('toolkit.deploy.Docker',return_value=self.docker), patch(
            'toolkit.deploy.verify',side_effect=checks
        ), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return deploy(self.request,self.root)

    def test_running_matching_release_uses_real_guards_and_records_success(self):
        with patch('toolkit.deploy.run_command') as mutate:
            self.assertEqual(self.invoke(),0)
        mutate.assert_not_called()
        self.assertEqual(read_state(self.root)['latest']['action'],'verify-only')

    def test_stopped_api_replacement_and_following_deployment(self):
        api=self.docker.items[0]
        api['State'].update(Status='exited',Running=False)
        self.docker.network['Containers'].pop(api['Id'])
        def replace(*args):
            self.assertEqual(read_state(self.root)['latest']['status'],'pending')
            api['Id']='4'*64
            api['State'].update(Status='running',Running=True)
            api['Config']['Labels'][LABEL+'project.config_files']=(
                str(self.root/'compose.yaml')+','+str(override_path(self.root)))
            self.docker.network['Containers'][api['Id']]={}
            return ''
        with patch('toolkit.deploy.run_command',side_effect=replace) as mutation:
            self.assertEqual(self.invoke(),0)
            mutation.assert_called_once()
        self.assertEqual(read_state(self.root)['latest']['action'],'replace')
        with patch('toolkit.deploy.run_command') as mutation:
            self.assertEqual(self.invoke(),0)
            mutation.assert_not_called()
        self.assertEqual(read_state(self.root)['latest']['action'],'verify-only')

    def test_startup_override_refused_before_recording_or_replacement(self):
        for key in ('command', 'entrypoint'):
            with self.subTest(key=key):
                self.docker.config['services']['api'][key] = []
                with patch('toolkit.deploy.run_command') as mutation:
                    self.assertEqual(self.invoke(), 4)
                mutation.assert_not_called()
                self.assertIsNone(read_state(self.root)['latest'])
                self.docker.config['services']['api'][key] = None
