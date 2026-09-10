"""Assemble local beta downloads. Does not publish or install anything."""
import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def installer_download_name(version):
    return f"TFT-Coach-Setup-{version}.exe"


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_checksums(directory):
    files = sorted(p for p in directory.iterdir()
                   if p.is_file() and p.name != 'SHA256SUMS.txt')
    (directory / 'SHA256SUMS.txt').write_text(
        ''.join(f'{sha256(p)}  {p.name}\n' for p in files), encoding='utf-8')


def verify_checksums(directory):
    for line in (directory / 'SHA256SUMS.txt').read_text(encoding='utf-8').splitlines():
        digest, name = line.split('  ', 1)
        if '/' in name or '\\' in name or ':' in name or name in ('.', '..'):
            raise ValueError('Unsafe checksum filename')
        path = directory / name
        if not path.is_file() or sha256(path) != digest:
            raise ValueError(f'Missing or changed release file: {name}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify', type=Path, help='Verify an existing release directory')
    args = parser.parse_args()
    if args.verify:
        verify_checksums(args.verify)
        print('Release checksums verified')
        return
    version = json.loads((ROOT / 'package.json').read_text())['version']
    if '-beta.' not in version:
        raise ValueError('Beta preparation requires a beta package version')
    installer = ROOT / 'dist-electron' / f'TFT Coach Setup {version}.exe'
    notices = ROOT / 'packaging/notices'
    if not installer.is_file() or not (notices / 'inventory.json').is_file():
        raise ValueError('Run npm run package first to build installer and notices')
    output = ROOT / 'dist-electron' / f'beta-{version}'
    output.mkdir(exist_ok=False)
    shutil.copy2(installer, output / installer_download_name(version))
    shutil.copy2(ROOT / 'docs/BETA_RELEASE_NOTES.md', output / 'RELEASE_NOTES.md')
    shutil.copy2(ROOT / 'docs/BETA_TESTING.md', output / 'TESTER_GUIDE.md')
    shutil.make_archive(str(output / 'THIRD_PARTY_NOTICES'), 'zip', notices)
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    changes = subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).splitlines()
    # Record that this local build has edits without exporting local filenames.
    manifest = {
        'version': version, 'source_base_commit': revision,
        'source_has_local_changes': bool(changes), 'platform': 'windows-x64',
        'signed': False, 'installer': installer_download_name(version),
        'installer_sha256': sha256(installer),
        'resource_sha256': {str(p.relative_to(ROOT / 'dist-electron/win-unpacked/resources')).replace('\\', '/'): sha256(p)
                            for p in sorted((ROOT / 'dist-electron/win-unpacked/resources/assets').rglob('*')) if p.is_file()},
    }
    (output / 'BUILD_MANIFEST.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    write_checksums(output)
    verify_checksums(output)
    print(f'Prepared beta downloads: {output}')


if __name__ == '__main__':
    main()
