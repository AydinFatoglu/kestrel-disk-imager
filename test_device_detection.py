"""Read-only detection tests; wxPython and raw-disk access are not required."""
import ast
import json
import re
import unittest
from pathlib import Path
from unittest.mock import Mock


def load_detection():
    # Load only the detection code so tests cannot initialize the GUI or disk APIs.
    source = Path(__file__).with_name('kestrel_disk_imager.py')
    tree = ast.parse(source.read_text(encoding='utf-8'))
    constants = {'READER_DESCRIPTION', 'DEVICE_SCAN_SCRIPT'}
    functions = {'is_card_reader', 'disk_rejection_reasons', 'scan_devices', 'scan_disks', 'disk_identity', 'write_image'}
    selected = [node for node in tree.body if
                (isinstance(node, ast.FunctionDef) and node.name in functions) or
                (isinstance(node, ast.Assign) and any(
                    isinstance(target, ast.Name) and target.id in constants for target in node.targets))]
    namespace = {'re': re, 'json': json, 'logger': Mock()}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(source), 'exec'), namespace)
    return namespace


class DeviceDetectionTests(unittest.TestCase):
    def setUp(self):
        self.code = load_detection()
        self.reader = {'InstanceId': 'USB\\reader',
                       'FriendlyName': 'USB SD Card Reader'}
        self.disk = {'Number': 1, 'FriendlyName': 'Mass Storage Device', 'BusType': 'USB',
                     'Size': 32 * 1024**3, 'UniqueId': 'card-a',
                     'PNPDeviceID': 'USBSTOR\\reader-slot', 'DeviceChain': [self.reader],
                     'IsBoot': False, 'IsSystem': False, 'IsReadOnly': False, 'IsOffline': False}

    def scan(self, disks, readers=None):
        self.code['powershell'] = Mock(return_value=json.dumps(
            {'Disks': disks, 'UsbDevices': readers or []}))
        return self.code['scan_devices']()

    def test_reader_description_is_recognized(self):
        self.assertTrue(self.code['is_card_reader'](self.reader))

    def test_reader_detection_does_not_depend_on_device_id(self):
        self.assertTrue(self.code['is_card_reader'](
            dict(self.reader, InstanceId='USB\\different-reader')))

    def test_reader_descriptions(self):
        for name in ('SanDisk Card Reader', 'USB SD Reader', 'USB SD/MMC', 'SDXC Reader'):
            with self.subTest(name=name):
                self.assertTrue(self.code['is_card_reader']({'Description': name}))

    def test_usb_disks_and_brand_alone_are_rejected(self):
        for name in ('SanDisk Ultra USB Device', 'SanDisk Cruzer Glide', 'USB Mass Storage Device',
                     'Seagate Expansion USB Device', 'Generic Flash Disk USB Device'):
            with self.subTest(name=name):
                self.assertFalse(self.code['is_card_reader']({'FriendlyName': name}))

    def test_empty_reader_has_no_write_target(self):
        disks, readers = self.scan([dict(self.disk, Size=0, IsOffline=True)], [self.reader])
        self.assertEqual(disks, [])
        self.assertEqual(readers, [self.reader])

    def test_usb_card_needs_no_drive_letter(self):
        disks, _ = self.scan([self.disk])
        self.assertEqual(disks, [self.disk])

    def test_native_cards_still_supported(self):
        for bus in ('SD', 'MMC'):
            with self.subTest(bus=bus):
                disk = dict(self.disk, BusType=bus, DeviceChain=[])
                self.assertEqual(self.scan([disk])[0], [disk])

    def test_unsafe_targets_excluded(self):
        cases = [dict(self.disk, **{key: True}) for key in
                 ('IsBoot', 'IsSystem', 'IsReadOnly', 'IsOffline')]
        cases += [dict(self.disk, Size=0), dict(self.disk, Size=1024),
                  dict(self.disk, BusType='NVMe'), dict(self.disk, BusType='SATA')]
        for disk in cases:
            with self.subTest(disk=disk):
                self.assertEqual(self.scan([disk])[0], [])

    def test_changed_or_missing_target_blocks_before_disk_access(self):
        for current in ([], [dict(self.disk, UniqueId='card-b')],
                        [dict(self.disk, PNPDeviceID='other')],
                        [dict(self.disk, Number=2)]):
            with self.subTest(current=current):
                self.code['scan_disks'] = Mock(return_value=current)
                lock = self.code['lock_volumes'] = Mock()
                with self.assertRaises(RuntimeError):
                    self.code['write_image'](1, None, 1024, None, self.disk)
                lock.assert_not_called()


if __name__ == '__main__':
    unittest.main()
