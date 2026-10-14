"""Optional .sha256 sidecar and known-image notice; no GUI or disk access."""
import ast
import re
import tempfile
import unittest
from pathlib import Path


def load_checksum():
    # Load only the checksum helpers so tests cannot initialize the GUI or disk APIs.
    source = Path(__file__).with_name('kestrel_disk_imager.py')
    tree = ast.parse(source.read_text(encoding='utf-8'))
    constants = {'FSDS_IMAGE_SHA256', 'SIDECAR_MAX_BYTES', 'SHA256_TOKEN'}
    functions = {'sidecar_sha256', 'image_check_note'}
    selected = [node for node in tree.body if
                (isinstance(node, ast.FunctionDef) and node.name in functions) or
                (isinstance(node, ast.Assign) and any(
                    isinstance(target, ast.Name) and target.id in constants for target in node.targets))]
    namespace = {'re': re}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(source), 'exec'), namespace)
    return namespace


class ImageChecksumTests(unittest.TestCase):
    def setUp(self):
        self.code = load_checksum()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.image = Path(self.temp.name) / 'os.img.xz'
        self.image.write_bytes(b'image')
        self.sidecar = Path(self.temp.name) / 'os.img.xz.sha256'
        self.hash = 'ab' * 32

    def test_missing_sidecar_allows_any_image(self):
        self.assertIsNone(self.code['sidecar_sha256'](self.image))

    def test_sidecar_with_file_name_is_parsed_lowercase(self):
        self.sidecar.write_text(self.hash.upper() + '  os.img.xz\n', encoding='utf-8')
        self.assertEqual(self.code['sidecar_sha256'](self.image), self.hash)

    def test_bare_hash_with_bom_is_parsed(self):
        self.sidecar.write_bytes(b'\xef\xbb\xbf' + self.hash.encode())
        self.assertEqual(self.code['sidecar_sha256'](self.image), self.hash)

    def test_binary_mode_marker_is_parsed(self):
        self.sidecar.write_text(self.hash + ' *os.img.xz\n', encoding='utf-8')
        self.assertEqual(self.code['sidecar_sha256'](self.image), self.hash)

    def test_malformed_sidecar_blocks_write(self):
        for content in ('', 'not a hash', self.hash[:-1], self.hash + 'f'):
            with self.subTest(content=content):
                self.sidecar.write_text(content, encoding='utf-8')
                with self.assertRaisesRegex(RuntimeError, 'engellendi'):
                    self.code['sidecar_sha256'](self.image)

    def test_known_fsds_image_gets_notice(self):
        known = self.code['FSDS_IMAGE_SHA256'].lower()
        self.assertEqual(self.code['image_check_note'](known, None), 'FSDS imajı doğrulandı.')
        self.assertEqual(self.code['image_check_note'](known, known), 'FSDS imajı doğrulandı.')

    def test_other_images_get_neutral_notice(self):
        note = self.code['image_check_note']
        self.assertIn('.sha256 dosyasıyla doğrulandı', note(self.hash, self.hash))
        self.assertIn('.sha256 dosyası yok', note(self.hash, None))


if __name__ == '__main__':
    unittest.main()
