"""Release safeguards; no certificate, network or real signing operation is used."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('kestrel_release', Path(__file__).with_name('release.py'))
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseSafeguards(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.source = root / 'unsigned.exe'
        self.output = root / 'signed' / 'app.exe'
        self.source.write_bytes(b'original executable')
        for name, value in [('UNSIGNED', self.source), ('SIGNED', self.output)]:
            p = patch.object(release, name, value)
            p.start()
            self.addCleanup(p.stop)

    def invoke_sign(self):
        with patch.object(sys, 'argv', ['release.py', 'sign', '--thumbprint', 'A' * 40]):
            release.main()

    def test_failed_sign_preserves_original_and_removes_only_candidate(self):
        with patch.object(release, 'signtool', return_value=Path('signtool.exe')), \
             patch.object(release, 'run', side_effect=subprocess.CalledProcessError(1, 'signtool')):
            with self.assertRaises(subprocess.CalledProcessError):
                self.invoke_sign()
        self.assertEqual(self.source.read_bytes(), b'original executable')
        self.assertFalse(self.output.exists())

    def test_existing_signed_output_is_not_overwritten(self):
        self.output.parent.mkdir()
        self.output.write_bytes(b'previous signed release')
        with patch.object(release, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'already exists'):
                self.invoke_sign()
            run.assert_not_called()
        self.assertEqual(self.output.read_bytes(), b'previous signed release')

    def test_missing_timestamp_is_rejected(self):
        with patch.object(release, 'signtool', return_value=Path('signtool.exe')), \
             patch.object(release, 'run'), \
             patch.object(release, 'signature', return_value={'Status': 'Valid', 'TimestampSigner': None}):
            with self.assertRaisesRegex(RuntimeError, 'timestamp'):
                release.verify(self.source)

    def test_build_cannot_overwrite_a_signed_executable(self):
        with patch.object(sys, 'argv', ['release.py', 'build']), \
             patch.object(release, 'signature', return_value={'Signer': 'Existing publisher'}), \
             patch.object(release, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'signed'):
                release.main()
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
