import tempfile
import unittest
from pathlib import Path

from prepare_beta import write_checksums, verify_checksums, installer_download_name


class ReleaseChecksumsTests(unittest.TestCase):
    def test_installer_download_name_survives_github_upload(self):
        self.assertEqual(installer_download_name("0.1.0-beta.1"),
                         "TFT-Coach-Setup-0.1.0-beta.1.exe")

    def test_release_files_with_spaces_roundtrip_and_tampering_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = root / 'TFT Coach Setup.exe'
            artifact.write_bytes(b'installer')
            write_checksums(root)
            verify_checksums(root)
            artifact.write_bytes(b'changed')
            with self.assertRaises(ValueError):
                verify_checksums(root)

    def test_missing_artifact_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = root / 'README.txt'
            artifact.write_text('instructions')
            write_checksums(root)
            artifact.unlink()
            with self.assertRaises(ValueError):
                verify_checksums(root)

    def test_manifest_cannot_reference_outside_release(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'SHA256SUMS.txt').write_text('0' * 64 + '  ../secret.txt\n')
            with self.assertRaises(ValueError):
                verify_checksums(root)


if __name__ == '__main__':
    unittest.main()
