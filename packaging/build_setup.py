"""Build an offline per-user Windows installer from an exact verified package.

No downloads occur here. Prepare the pinned Inno Setup compiler under build/
first, then run with the bundled Python. Output is a new directory under dist/.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from verify_package import verify

APP_ID = '{B148E74E-40DC-4F99-86BD-208F661609A6}'


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def inventory(package: Path) -> list[Path]:
    """Refuse changed, extra, redirected or unsafe inputs before invoking ISCC."""
    files = []
    names = set()
    if any((package / name).exists() for name in ('data', 'logs', 'temp', 'downloads', 'installed.marker')):
        raise RuntimeError('Package contains user data or an installed marker; build a new clean package')
    for line in (package / 'PACKAGE.sha256').read_text(encoding='utf-8').splitlines():
        expected, name = line.split(maxsplit=1)
        relative = Path(name)
        if (relative.is_absolute() or '..' in relative.parts or name in names
                or any(character in name for character in ('"', ';', '{', '}', '\n', '\r'))):
            raise RuntimeError(f'Unsafe package input: {name}')
        target = package / relative
        if not target.resolve().is_relative_to(package) or not target.is_file():
            raise RuntimeError(f'Missing package input: {name}')
        if any(parent.is_symlink() or parent.is_junction() for parent in (target, *target.parents) if parent != ROOT.parent):
            raise RuntimeError(f'Redirected package input: {name}')
        if digest(target) != expected:
            raise RuntimeError(f'Changed package input: {name}')
        names.add(name)
        files.append(relative)
    actual = {path.relative_to(package).as_posix() for path in package.rglob('*') if path.is_file()}
    if actual != names | {'PACKAGE.sha256'}:
        raise RuntimeError('Package contains unlisted files or user data; build a new clean package')
    return sorted(files + [Path('PACKAGE.sha256')])


def inno_string(value: Path | str) -> str:
    value = str(value)
    if any(character in value for character in ('"', '\n', '\r')):
        raise RuntimeError('Invalid installer build path')
    return '"' + value + '"'


def check_previous_setup(directory: Path) -> None:
    if directory.is_symlink() or directory.is_junction():
        raise RuntimeError('Refusing to archive a redirected installer output')
    expected = {'CartoonDownloader-Setup.exe', 'SETUP.json', 'SHA256SUMS.txt', 'BUILD.log'}
    entries = list(directory.iterdir())
    if {path.name for path in entries} != expected or any(
            not path.is_file() or path.is_symlink() or path.is_junction() for path in entries):
        raise RuntimeError('Existing installer output contains unknown files; it will not be moved')
    metadata = json.loads((directory / 'SETUP.json').read_text(encoding='utf-8'))
    if (metadata.get('product') != 'Cartoon Downloader Desktop'
            or digest(directory / 'CartoonDownloader-Setup.exe') != metadata.get('installer_sha256')):
        raise RuntimeError('Existing installer output is not an intact generated build')


def main() -> int:
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--iscc', type=Path, default=ROOT / 'build/installer-tools/inno-7.1.0/ISCC.exe')
    parser.add_argument('--archive-existing', action='store_true',
                        help='Preserve an existing clean installer under build/ after successful compilation')
    args = parser.parse_args()
    if os.name != 'nt':
        parser.error('Windows is required')
    package = args.package.resolve()
    if not package.is_relative_to((ROOT / 'dist').resolve()) or package == ROOT / 'dist':
        parser.error('Expected a clean package directory inside this workspace dist/')
    files = inventory(package)
    errors = verify(package)
    if errors:
        raise RuntimeError('\n'.join(errors))
    metadata = json.loads((package / 'RELEASE.json').read_text(encoding='utf-8'))
    version = metadata['version']
    if metadata.get('product') != 'Cartoon Downloader Desktop' or not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise RuntimeError('Unexpected package product/version')
    compiler = args.iscc.resolve()
    lock = json.loads((ROOT / 'packaging/installer-toolchain.json').read_text(encoding='utf-8'))
    if not compiler.is_file() or digest(compiler) != lock['compiler_sha256']:
        raise RuntimeError('The pinned Inno Setup compiler is missing or changed')
    destination = ROOT / 'dist' / f'CartoonDownloader-{version}-Setup'
    if destination.exists() and not args.archive_existing:
        parser.error('Installer output already exists; preserve it and choose a new app version')
    if destination.exists():
        check_previous_setup(destination)
    work = Path(tempfile.mkdtemp(prefix='setup-', dir=ROOT / 'build'))
    output = work / 'output'
    output.mkdir()
    print('Installer build workspace:', work, flush=True)
    shutil.copyfile(ROOT / 'packaging/installer.iss', work / 'installer.iss')
    (work / 'BuildConfig.iss').write_text(
        f'#define AppVersion {inno_string(version)}\n'
        f'#define PackageDir {inno_string(package)}\n'
        f'#define OutputDir {inno_string(output)}\n', encoding='utf-8-sig')
    terms = ('Cartoon Downloader — installation of bundled components\n\n'
             'This installer includes Microsoft WebView2 Fixed Version. Acceptance below '
             'applies to its license terms, reproduced here in full. Other bundled '
             'component notices follow.\n\n')
    terms += (package / 'tools/webview2/RUNTIME-LICENSE.txt').read_text(encoding='utf-8')
    terms += '\n\n' + (package / 'THIRD_PARTY_NOTICES.md').read_text(encoding='utf-8')
    (work / 'InstallationTerms.txt').write_text(terms, encoding='utf-8-sig')
    (work / 'installed.marker').write_text('Installed resources; user data lives in LocalAppData/Cartoon Downloader.\n', encoding='utf-8')
    shutil.copyfile(ROOT / 'INSTALLATION.md', work / 'INSTALLATION.md')
    shutil.copyfile(compiler.parent / 'License.txt', work / 'INNO-SETUP-LICENSE.txt')
    payload = []
    owned = []
    for relative in files:
        folder = '{app}' if relative.parent == Path('.') else '{app}\\' + str(relative.parent)
        payload.append(f'Source: {inno_string(package / relative)}; DestDir: {inno_string(folder)}; Flags: ignoreversion\n')
        owned.append(f'{digest(package / relative)}  {relative.as_posix()}\n')
    for source, name in (('InstallationTerms.txt', 'INSTALLATION-TERMS.txt'),
                         ('installed.marker', 'installed.marker'), ('INSTALLATION.md', 'INSTALLATION.md'),
                         ('INNO-SETUP-LICENSE.txt', 'INNO-SETUP-LICENSE.txt')):
        # A newer source package can already contain the installation guide.
        if Path(name) not in files:
            payload.append(f'Source: {inno_string(work / source)}; DestDir: "{{app}}"; DestName: "{name}"; Flags: ignoreversion\n')
            owned.append(f'{digest(work / source)}  {name}\n')
    (work / 'INSTALLED.sha256').write_text(''.join(owned), encoding='utf-8')
    payload.append(f'Source: {inno_string(work / "INSTALLED.sha256")}; DestDir: "{{app}}"; Flags: ignoreversion\n')
    (work / 'Payload.iss').write_text(''.join(payload), encoding='utf-8-sig')
    with (work / 'compile.log').open('w', encoding='utf-8') as log:
        result = subprocess.run([str(compiler), str(work / 'installer.iss')], cwd=work,
                                stdout=log, stderr=subprocess.STDOUT, timeout=1200,
                                creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError((work / 'compile.log').read_text(encoding='utf-8', errors='replace')[-6000:])
    installer = output / 'CartoonDownloader-Setup.exe'
    if not installer.is_file():
        raise RuntimeError('Compiler did not produce the installer')
    setup_metadata = {'product': metadata['product'], 'version': version, 'app_id': APP_ID,
                      'architecture': 'windows-x64', 'scope': 'current-user',
                      'package_sha256': digest(package / 'PACKAGE.sha256'),
                      'source_package': str(package.relative_to(ROOT)),
                      'compiler': lock, 'installer_sha256': digest(installer),
                      'installer_bytes': installer.stat().st_size,
                      'signed': False, 'recipe': 'packaging/build_setup.py'}
    (output / 'SETUP.json').write_text(json.dumps(setup_metadata, indent=2) + '\n', encoding='utf-8')
    (output / 'SHA256SUMS.txt').write_text(f'{digest(installer)}  {installer.name}\n', encoding='utf-8')
    shutil.copyfile(work / 'compile.log', output / 'BUILD.log')
    if destination.exists():
        check_previous_setup(destination)
        archive = ROOT / 'build' / ('previous-setup-' + uuid.uuid4().hex)
        if (not destination.resolve().is_relative_to((ROOT / 'dist').resolve())
                or not archive.resolve().is_relative_to((ROOT / 'build').resolve())):
            raise RuntimeError('Unsafe installer archive path')
        archive.mkdir()
        destination.rename(archive / destination.name)
        print('Previous installer preserved:', archive, flush=True)
    output.rename(destination)
    subprocess.run(['icacls.exe', str(destination), '/reset', '/T', '/C', '/Q'],
                   check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    print(json.dumps({'installer': str(destination / installer.name), 'version': version,
                      'bytes': setup_metadata['installer_bytes'], 'sha256': setup_metadata['installer_sha256']},
                     ensure_ascii=False), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
