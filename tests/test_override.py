import json
from pathlib import Path
import tempfile
import unittest

from toolkit.docker import InspectionError
from toolkit.override import override_path, read_override, write_override, config_label_allowed
from toolkit.state import operation_session

IMAGE = 'sha256:' + 'a'*64


class OverrideTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def test_missing_override_is_read_only(self):
        self.assertIsNone(read_override(self.root))
        self.assertFalse((self.root / '.runtime').exists())

    def test_exact_image_only_override_round_trip(self):
        with operation_session(self.root):
            write_override(self.root, IMAGE)
        self.assertEqual(read_override(self.root), IMAGE)
        self.assertEqual(json.loads(override_path(self.root).read_text()),
                         {'services': {'api': {'image': IMAGE}}})

    def test_extra_service_or_field_is_refused_without_overwrite(self):
        for value in ({'services': {'db': {'image': IMAGE}}},
                      {'services': {'api': {'image': IMAGE, 'privileged': True}}}):
            with operation_session(self.root):
                override_path(self.root).write_text(json.dumps(value))
                before = override_path(self.root).read_bytes()
                with self.assertRaises(InspectionError):
                    write_override(self.root, IMAGE)
                self.assertEqual(override_path(self.root).read_bytes(), before)

    def test_symlink_is_refused(self):
        with operation_session(self.root):
            target = self.root / 'external'
            target.write_text('private')
            override_path(self.root).symlink_to(target)
            with self.assertRaises(InspectionError):
                read_override(self.root)
            self.assertEqual(target.read_text(), 'private')

    def test_only_api_may_have_exact_toolkit_override_label(self):
        base = str(self.root / 'compose.yaml')
        label = base + ',' + str(override_path(self.root))
        self.assertTrue(config_label_allowed(self.root, 'db', base))
        self.assertFalse(config_label_allowed(self.root, 'api', label))
        with operation_session(self.root):
            write_override(self.root, IMAGE)
        self.assertTrue(config_label_allowed(self.root, 'api', label))
        self.assertFalse(config_label_allowed(self.root, 'db', label))
        self.assertFalse(config_label_allowed(self.root, 'api', label + ',/foreign'))

    def test_override_label_image_mismatch_is_refused(self):
        from test_preflight import FakeDocker
        from toolkit.preflight import check_resources, LABEL
        docker = FakeDocker(self.root)
        with operation_session(self.root):
            write_override(self.root, 'sha256:' + 'b'*64)
        docker.items[0]['Config']['Labels'][LABEL+'project.config_files'] = (
            str(self.root/'compose.yaml') + ',' + str(override_path(self.root)))
        with self.assertRaises(InspectionError):
            check_resources(docker.items, self.root)

    def test_actual_toolkit_owned_api_passes_resource_check(self):
        from test_preflight import FakeDocker
        from toolkit.preflight import check_resources, LABEL
        docker = FakeDocker(self.root)
        with operation_session(self.root):
            write_override(self.root, IMAGE)
        docker.items[0]['Config']['Labels'][LABEL+'project.config_files'] = (
            str(self.root/'compose.yaml') + ',' + str(override_path(self.root)))
        self.assertEqual(check_resources(docker.items, self.root)['api']['Image'], IMAGE)
