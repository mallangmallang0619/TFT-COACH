"""Collect available dependency notices using the Windows packaging venv."""
import hashlib
import importlib.metadata
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'packaging/notices'


def copy_notice(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return target.relative_to(OUTPUT).as_posix()


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    entries = []
    # Include the entire builder environment conservatively. Some entries are
    # build-only; this is an inventory, not an exact binary dependency graph.
    for distribution in sorted(importlib.metadata.distributions(), key=lambda d: d.metadata['Name'].lower()):
        name = distribution.metadata['Name']
        safe = re.sub(r'[^A-Za-z0-9_.-]', '_', name)
        notices = []
        for file in distribution.files or []:
            if re.match(r'(?i)^(license|licence|copying|notice|authors)', Path(str(file)).name):
                source = Path(distribution.locate_file(file))
                if source.is_file():
                    target = OUTPUT / 'python' / safe / str(len(notices)) / source.name
                    notices.append(copy_notice(source, target))
        entries.append({'ecosystem': 'python-build-environment', 'name': name,
                        'version': distribution.version, 'notices': notices,
                        'license': distribution.metadata.get('License-Expression') or distribution.metadata.get('License') or 'Unspecified'})
    # Packages included in Electron main or the bundled React application.
    for base, names in [(ROOT / 'node_modules', ['adm-zip', 'electron']),
                        (ROOT / 'frontend/node_modules', ['react', 'react-dom', 'scheduler', 'loose-envify', 'js-tokens'])]:
        for name in names:
            package = base / name
            metadata = json.loads((package / 'package.json').read_text(encoding='utf-8'))
            notices = [copy_notice(p, OUTPUT / 'javascript' / name / p.name)
                       for p in package.iterdir() if p.is_file() and re.match(r'(?i)^(license|notice|copying)', p.name)]
            entries.append({'ecosystem': 'javascript', 'name': name, 'version': metadata['version'],
                            'license': metadata.get('license', 'Unspecified'), 'notices': notices})
    for filename in ['LICENSE', 'LICENSES.chromium.html']:
        source = ROOT / 'node_modules/electron/dist' / filename
        if source.exists():
            copy_notice(source, OUTPUT / 'electron' / filename)
    copy_notice(Path(sys.base_prefix) / 'LICENSE.txt', OUTPUT / 'python-runtime/LICENSE.txt')
    copy_notice(ROOT / 'LICENSE', OUTPUT / 'TFT-COACH-LICENSE.txt')
    native = []
    for file in sorted((ROOT / 'packaging/tesseract').rglob('*')):
        if not file.is_file():
            continue
        if 'doc' in file.relative_to(ROOT / 'packaging/tesseract').parts:
            copy_notice(file, OUTPUT / 'tesseract' / file.relative_to(ROOT / 'packaging/tesseract'))
        else:
            native.append({'file': file.relative_to(ROOT / 'packaging/tesseract').as_posix(),
                           'sha256': hashlib.sha256(file.read_bytes()).hexdigest()})
    inventory = {'python_version': sys.version.split()[0], 'packages': entries,
                 'tesseract_files': native,
                 'review_remaining': [
                     'Map every Tesseract DLL and traineddata file to its upstream notices and redistribution requirements.',
                     'Review game artwork/model provenance and TFT Academy/tactics.tools cached-data distribution.',
                     'Reconcile builder-environment inventory against the actual packaged binary dependency graph.']}
    (OUTPUT / 'inventory.json').write_text(json.dumps(inventory, indent=2) + '\n', encoding='utf-8')
    (OUTPUT / 'README.txt').write_text(
        'Available third-party notices for TFT Coach. See inventory.json for versions, scope,\n'
        'and outstanding review. This collection is not a completed redistribution audit.\n', encoding='utf-8')
    print(f'Collected notices for {len(entries)} packages')


if __name__ == '__main__':
    main()
