import tempfile
import unittest
from pathlib import Path
from app_paths import resolve_paths


class AppPathsTests(unittest.TestCase):
    def test_packaged_paths_keep_writes_outside_install_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = resolve_paths(True, root / 'resources/backend/app.exe',
                                  {'TFT_COACH_USER_DATA': str(root / 'User Space 한글')})
            self.assertEqual(paths.resources, root / 'resources')
            self.assertEqual(paths.logs, root / 'User Space 한글/logs')
            self.assertEqual(paths.diagnostics, root / 'User Space 한글/diagnostics')
            self.assertNotEqual(paths.data, paths.resources)

    def test_source_paths_preserve_existing_datasets(self):
        paths = resolve_paths(False, Path('python.exe'), {'TFT_COACH_USER_DATA': 'unused'})
        self.assertEqual(paths.training, paths.resources / 'backend/_training')


if __name__ == '__main__':
    unittest.main()
