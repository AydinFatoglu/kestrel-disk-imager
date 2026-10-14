"""Exercise destructive write sequencing with an in-memory disk only."""
import ast
import ctypes
import hashlib
import io
import logging
import lzma
import os
import queue
import tempfile
import threading
import types
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock, patch


class DiskPreparationTests(unittest.TestCase):
    def setUp(self):
        source = Path(__file__).with_name('kestrel_disk_imager.py')
        tree = ast.parse(source.read_text(encoding='utf-8'))
        names = {'disk_identity', 'write_image', 'image_blocks', 'write_block', 'verify_image'}
        nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
        self.target = dict(Number=1, UniqueId='card', PNPDeviceID='usb', Size=4096, BusType='USB')
        self.disk = io.BytesIO(b'old data' * 512)
        self.image = b'P' * 512 + b'D' * 1024
        self.events = []
        self.handle = Mock()
        self.lock = Mock()
        self.lock.Close.side_effect = lambda: self.events.append('unlock')
        self.api = Mock()
        self.api.CreateFile.return_value = self.handle
        self.api.SetFilePointer.side_effect = lambda h, offset, origin: self.disk.seek(offset, origin)
        def read(handle, length):
            self.events.append(('read', self.disk.tell()))
            return 0, self.disk.read(length)
        self.api.ReadFile.side_effect = read
        self.api.WriteFile.side_effect = self.write
        self.api.DeviceIoControl.side_effect = self.control
        self.api.FlushFileBuffers.side_effect = lambda h: self.events.append('flush')
        class DiskError(Exception):
            winerror = 5
        self.error = DiskError
        self.code = dict(logger=Mock(), queue=queue, threading=threading,
                         contextmanager=contextmanager, PREFETCH_BLOCKS=2,
                         DIRECT_IO_UNSUPPORTED=(1, 50, 87), AlignedDiskReader=Mock(),
                         win32file=self.api,
                         win32con=types.SimpleNamespace(GENERIC_READ=1, GENERIC_WRITE=2,
                             FILE_SHARE_READ=1, FILE_SHARE_WRITE=2, OPEN_EXISTING=3,
                             FILE_FLAG_WRITE_THROUGH=0, FILE_BEGIN=0),
                         pywintypes=types.SimpleNamespace(error=DiskError),
                         IOCTL_DISK_DELETE_DRIVE_LAYOUT=0x7C100,
                         IOCTL_DISK_UPDATE_PROPERTIES=0x70140, CHUNK=512,
                         scan_disks=Mock(return_value=[self.target]),
                         lock_volumes=Mock(return_value=[self.lock]),
                         lzma=types.SimpleNamespace(open=lambda *args: io.BytesIO(self.image)))
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), self.code)

    def write(self, handle, data):
        self.events.append(('write', self.disk.tell()))
        # Force partial writes to exercise both body and partition-table loops.
        return 0, self.disk.write(data[:128])

    def control(self, handle, code, *args):
        self.events.append(code)
        if code == 0x7C100:
            self.disk.seek(0)
            self.disk.write(bytes(512))

    def run_write(self, target=None):
        self.code['write_image'](1, Path('unused.img.xz'), len(self.image), Mock(),
                                 target or self.target)

    def test_clean_then_body_then_partition_table_then_refresh(self):
        self.run_write()
        self.assertEqual(self.disk.getvalue()[:len(self.image)], self.image)
        writes = [event[1] for event in self.events if isinstance(event, tuple) and event[0] == 'write']
        self.assertEqual(writes[0], 512)
        self.assertEqual(writes[-4:], [0, 128, 256, 384])
        self.assertEqual(self.events[0], 0x7C100)
        self.assertLess(self.events.index('flush'), self.events.index(('write', 0)))
        self.assertLess(self.events.index(('read', 1024)), self.events.index(('write', 0)))
        self.assertLess(self.events.index(('write', 0)), self.events.index(('read', 0)))
        self.assertLess(self.events.index('unlock'), self.events.index(0x70140))
        self.handle.Close.assert_called_once()

    def test_clean_failure_prevents_image_write_and_releases_handles(self):
        self.api.DeviceIoControl.side_effect = self.error('access denied')
        with self.assertRaisesRegex(RuntimeError, 'temizlenemedi'):
            self.run_write()
        self.api.WriteFile.assert_not_called()
        self.lock.Close.assert_called_once()
        self.handle.Close.assert_called_once()

    def test_changed_device_is_never_cleaned(self):
        with self.assertRaises(RuntimeError):
            self.run_write(dict(self.target, PNPDeviceID='other'))
        self.api.CreateFile.assert_not_called()
        self.api.DeviceIoControl.assert_not_called()

    def test_body_failure_does_not_publish_partition_table(self):
        self.api.WriteFile.side_effect = IOError('write failed')
        with self.assertRaises(IOError):
            self.run_write()
        self.assertEqual(self.disk.getvalue()[:512], bytes(512))
        self.assertNotIn(0x70140, self.events)
        self.lock.Close.assert_called_once()
        self.handle.Close.assert_called_once()

    def test_volume_controls_do_not_depend_on_win32con_exports(self):
        source = Path(__file__).with_name('kestrel_disk_imager.py')
        tree = ast.parse(source.read_text(encoding='utf-8'))
        constants = {'FSCTL_LOCK_VOLUME', 'FSCTL_DISMOUNT_VOLUME'}
        nodes = [n for n in tree.body if
                 (isinstance(n, ast.FunctionDef) and n.name == 'lock_volumes') or
                 (isinstance(n, ast.Assign) and any(
                     isinstance(t, ast.Name) and t.id in constants for t in n.targets))]
        namespace = dict(self.code, volumes_on_disk=Mock(return_value=['E']))
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), namespace)
        self.assertEqual(namespace['lock_volumes'](1), [self.handle])
        self.assertEqual([c.args[1] for c in self.api.DeviceIoControl.call_args_list],
                         [0x90018, 0x90020])

    def enable_direct_reader(self):
        self.target.update(LogicalSectorSize=512, PhysicalSectorSize=4096)
        reader = Mock()
        self.code['AlignedDiskReader'].return_value = reader
        source = io.BytesIO(self.image)
        reader.read.side_effect = source.read
        reader.seek.side_effect = source.seek
        return reader

    def test_direct_verification_reads_every_byte_and_closes_reader(self):
        reader = self.enable_direct_reader()
        self.run_write()
        self.assertEqual(sum(c.args[0] for c in reader.read.call_args_list), len(self.image))
        self.api.ReadFile.assert_not_called()
        reader.close.assert_called_once()

    def test_unsupported_direct_open_falls_back_to_full_verification(self):
        self.enable_direct_reader()
        error = self.error('unsupported')
        error.winerror = 50
        self.code['AlignedDiskReader'].side_effect = error
        self.run_write()
        self.assertEqual(sum(c.args[1] for c in self.api.ReadFile.call_args_list), len(self.image))

    def test_unsupported_first_direct_read_falls_back(self):
        reader = self.enable_direct_reader()
        error = self.error('unsupported')
        error.winerror = 87
        reader.read.side_effect = error
        self.run_write()
        reader.close.assert_called_once()
        self.assertEqual(sum(c.args[1] for c in self.api.ReadFile.call_args_list), len(self.image))

    def test_media_error_never_falls_back(self):
        reader = self.enable_direct_reader()
        error = self.error('CRC error')
        error.winerror = 23
        reader.read.side_effect = error
        with self.assertRaises(self.error):
            self.run_write()
        self.api.ReadFile.assert_not_called()
        reader.close.assert_called_once()
        self.assertNotIn(0x70140, self.events)

    def test_later_direct_read_failure_never_falls_back(self):
        reader = self.enable_direct_reader()
        error = self.error('unsupported after successful read')
        error.winerror = 87
        reader.read.side_effect = [self.image[512:1024], error]
        with self.assertRaises(self.error):
            self.run_write()
        self.api.ReadFile.assert_not_called()
        reader.close.assert_called_once()

    def test_direct_data_mismatch_never_falls_back(self):
        reader = self.enable_direct_reader()
        reader.read.side_effect = lambda length: b'X' * length
        with self.assertRaisesRegex(IOError, 'offset 512'):
            self.run_write()
        self.api.ReadFile.assert_not_called()
        reader.close.assert_called_once()
        self.assertNotIn(0x70140, self.events)

    def test_buffered_short_read_fails(self):
        self.api.ReadFile.side_effect = lambda h, length: (0, b'P')
        with self.assertRaisesRegex(IOError, 'offset 512'):
            self.run_write()
        self.assertNotIn(0x70140, self.events)

    def test_oversized_source_is_not_written_past_expected_length(self):
        self.image += b'X' * 512
        with self.assertRaisesRegex(IOError, 'uzunluğu'):
            self.code['write_image'](1, Path('unused'), 1536, Mock(), self.target)
        self.assertTrue(all(event[1] < 1536 for event in self.events if isinstance(event, tuple)))
        self.assertEqual(self.disk.getvalue()[:512], bytes(512))

    def test_decoder_error_reaches_writer_and_thread_stops(self):
        class BadSource(io.BytesIO):
            def read(self, length):
                if self.tell() >= 512:
                    raise IOError('decoder failure')
                return super().read(length)
        self.code['lzma'].open = lambda *args: BadSource(self.image)
        with self.assertRaisesRegex(IOError, 'decoder failure'):
            self.run_write()
        self.assertFalse(any(t.name == 'ImageDecoder' for t in threading.enumerate()))
        self.assertEqual(self.disk.getvalue()[:512], bytes(512))

    def test_early_consumer_exit_stops_full_queue_producer(self):
        self.image *= 100
        with self.code['image_blocks'](Path('unused')) as blocks:
            next(blocks)
        self.assertFalse(any(t.name == 'ImageDecoder' for t in threading.enumerate()))

    def test_partition_table_stays_hidden_during_body_verification(self):
        original_read = self.api.ReadFile.side_effect
        def protected_read(handle, length):
            if self.disk.tell() >= 512:
                self.assertEqual(self.disk.getvalue()[:512], bytes(512))
            return original_read(handle, length)
        self.api.ReadFile.side_effect = protected_read
        self.run_write()

    def test_body_mismatch_does_not_commit_partition_table(self):
        self.api.ReadFile.side_effect = lambda handle, length: (0, b'X' * length)
        with self.assertRaisesRegex(IOError, 'offset 512'):
            self.run_write()
        self.assertEqual(self.disk.getvalue()[:512], bytes(512))
        self.assertNotIn(0x70140, self.events)

    def test_final_prefix_readback_failure_blocks_success_and_refresh(self):
        original_read = self.api.ReadFile.side_effect
        def corrupt_prefix(handle, length):
            if self.disk.tell() == 0:
                return 0, b'X' * length
            return original_read(handle, length)
        self.api.ReadFile.side_effect = corrupt_prefix
        with self.assertRaisesRegex(IOError, 'ilk blok doğrulanamadı'):
            self.run_write()
        self.assertNotIn(0x70140, self.events)
        self.handle.Close.assert_called_once()
        self.lock.Close.assert_called_once()

    def test_single_block_image_is_committed_and_verified(self):
        self.image = self.image[:512]
        self.run_write()
        self.assertEqual(self.disk.getvalue()[:512], self.image)
        self.api.ReadFile.assert_called_once_with(self.handle, 512)


@unittest.skipUnless(os.name == 'nt', 'Windows native I/O')
class WindowsFileIOTests(unittest.TestCase):
    """Use disposable regular files; never open a physical disk."""
    def setUp(self):
        import win32file
        import win32con
        import pywintypes
        source = Path(__file__).with_name('kestrel_disk_imager.py')
        tree = ast.parse(source.read_text(encoding='utf-8'))
        nodes = [n for n in tree.body if
                 (isinstance(n, ast.FunctionDef) and n.name in ('write_block', 'image_blocks', 'verify_image')) or
                 (isinstance(n, ast.ClassDef) and n.name == 'AlignedDiskReader')]
        self.code = dict(ctypes=ctypes, win32file=win32file, win32con=win32con,
                         queue=queue, threading=threading, contextmanager=contextmanager,
                         lzma=lzma, CHUNK=4 * 1024 * 1024, PREFETCH_BLOCKS=2,
                         pywintypes=pywintypes, DIRECT_IO_UNSUPPORTED=(1, 50, 87),
                         logger=logging.getLogger('test'))
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), self.code)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'disposable.bin'
        self.data = bytes(range(256)) * (16384 + 2)

    def test_native_unbuffered_read_with_aligned_buffer_and_final_sector(self):
        api, con = self.code['win32file'], self.code['win32con']
        self.path.write_bytes(self.data)
        real_create = api.CreateFile
        def open_regular_file(path, access, sharing, security, disposition, flags, template):
            self.assertEqual(access, con.GENERIC_READ)
            self.assertEqual(flags, con.FILE_FLAG_NO_BUFFERING)
            return real_create(str(self.path), access, sharing, security, disposition, flags, template)
        with patch.object(api, 'CreateFile', side_effect=open_regular_file):
            reader = self.code['AlignedDiskReader'](999, 512, 4096)
            try:
                self.assertEqual(reader.buffer % 4096, 0)
                self.assertEqual(reader.read(4 * 1024 * 1024), self.data[:-512])
                self.assertEqual(reader.read(512), self.data[-512:])
                with self.assertRaises(ValueError):
                    reader.read(513)
            finally:
                reader.close()
        self.assertEqual(self.path.read_bytes(), self.data)

    def test_native_writefile_accepts_memoryview(self):
        api, con = self.code['win32file'], self.code['win32con']
        handle = api.CreateFile(str(self.path), con.GENERIC_WRITE, 0, None,
                                con.CREATE_ALWAYS, con.FILE_FLAG_WRITE_THROUGH, None)
        try:
            self.code['write_block'](handle, self.data[:4 * 1024 * 1024])
            self.code['write_block'](handle, self.data[-512:])
        finally:
            handle.Close()
        self.assertEqual(self.path.read_bytes(), self.data)

    def test_real_xz_pipeline_preserves_source_and_block_order(self):
        self.path.write_bytes(lzma.compress(self.data))
        before = hashlib.sha256(self.path.read_bytes()).digest()
        with self.code['image_blocks'](self.path) as blocks:
            decoded = list(blocks)
        self.assertEqual([len(b) for b in decoded], [4 * 1024 * 1024, 512])
        self.assertEqual(b''.join(decoded), self.data)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).digest(), before)

    def test_native_body_verification_then_commit_and_direct_prefix_readback(self):
        api, con = self.code['win32file'], self.code['win32con']
        prefix = self.data[:4 * 1024 * 1024]
        self.path.write_bytes(bytes(len(prefix)) + self.data[len(prefix):])
        source = Path(self.temp.name) / 'source.img.xz'
        source.write_bytes(lzma.compress(self.data))
        handle = api.CreateFile(str(self.path), con.GENERIC_READ | con.GENERIC_WRITE,
                                con.FILE_SHARE_READ | con.FILE_SHARE_WRITE, None,
                                con.OPEN_EXISTING, con.FILE_FLAG_WRITE_THROUGH, None)
        real_create = api.CreateFile
        def open_regular_file(path, *args):
            return real_create(str(self.path), *args)
        try:
            with patch.object(api, 'CreateFile', side_effect=open_regular_file):
                count = self.code['verify_image'](handle, 999, source, len(self.data),
                    dict(LogicalSectorSize=512, PhysicalSectorSize=4096), Mock(), prefix)
            self.assertEqual(count, len(self.data))
        finally:
            handle.Close()
        self.assertEqual(self.path.read_bytes(), self.data)


if __name__ == '__main__':
    unittest.main()
