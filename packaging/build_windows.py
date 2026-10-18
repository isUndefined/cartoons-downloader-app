"""Build a Windows GUI launcher and a compiled, allowlisted application folder.

Run with the bundled Python. Only build/ and a new child of dist/ are written;
existing output directories are never replaced or recursively removed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cartoon_downloader import __version__
from verify_package import verify
from compiled_backend import build_backend, TEXT_ASSETS


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def run(command: list[str]) -> str:
    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8',
                            errors='replace', timeout=120,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return result.stdout.strip()


def copy_tree(source: Path, destination: Path) -> None:
    if source.is_symlink() or source.is_junction():
        raise RuntimeError(f'Refusing redirected package input: {source}')
    destination.mkdir(parents=True)
    for item in sorted(source.iterdir()):
        # Symbols are useful in the development runtime, but not in a release.
        if item.name == '__pycache__' or item.suffix.lower() in {'.pyc', '.pdb'}:
            continue
        if item.is_symlink() or item.is_junction():
            raise RuntimeError(f'Refusing redirected package input: {item}')
        if item.is_dir():
            copy_tree(item, destination / item.name)
        elif item.is_file():
            shutil.copyfile(item, destination / item.name)


def main() -> int:
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist' / f'CartoonDownloader-{__version__}')
    parser.add_argument('--archive-existing', action='store_true',
                        help='Preserve an existing clean build under build/ before publishing the replacement')
    args = parser.parse_args()
    if os.name != 'nt':
        parser.error('Windows is required to compile the launcher')
    destination = args.output.resolve()
    distribution = (ROOT / 'dist').resolve()
    if (not distribution.is_relative_to(ROOT) or not destination.is_relative_to(distribution)
            or destination == distribution):
        parser.error('Output must be a new directory inside this workspace dist/')
    if destination.exists() and not args.archive_existing:
        parser.error('Output already exists; choose a new --output directory')
    def check_previous_build():
        if destination.is_symlink() or destination.is_junction():
            raise RuntimeError('Refusing to move a redirected output directory')
        metadata = json.loads((destination / 'RELEASE.json').read_text(encoding='utf-8'))
        if metadata.get('product') != 'Cartoon Downloader Desktop':
            raise RuntimeError('Existing output is not a generated application package')
        if any((destination / name).exists() for name in ('data', 'logs', 'temp', 'downloads', 'installed.marker')):
            raise RuntimeError('Existing output contains user data or an installed marker; choose a new output')
    if destination.exists():
        check_previous_build()
    compiler = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    if not compiler.is_file():
        raise RuntimeError('The Windows .NET Framework C# compiler is missing')
    errors = verify(ROOT)
    if errors:
        raise RuntimeError('\n'.join(errors))
    if shutil.disk_usage(ROOT).free < 2 * 1024 ** 3:
        raise RuntimeError('At least 2 GiB of free workspace space is required')
    (ROOT / 'build').mkdir(exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='windows-', dir=ROOT / 'build'))
    package = work / 'CartoonDownloader'
    package.mkdir()
    print('Build workspace:', work, flush=True)
    # Explicit inputs exclude working databases, logs, media, test fixtures and
    # previous releases regardless of what else exists in the project folder.
    for name in ('tools',):
        copy_tree(ROOT / name, package / name)
    copy_tree(ROOT / 'runtime/python/licenses', package / 'runtime/python/licenses')
    shutil.copyfile(ROOT / 'runtime/python/PYTHON.json', package / 'runtime/python/PYTHON.json')
    for path in sorted((ROOT / 'static').rglob('*')):
        if path.is_file() and path.suffix.lower() not in TEXT_ASSETS:
            target = package / 'static' / path.relative_to(ROOT / 'static')
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
    for name in ('THIRD_PARTY_NOTICES.md',):
        shutil.copyfile(ROOT / name, package / name)
    guide = (ROOT / 'INSTALLATION.md').read_text(encoding='utf-8').split('## Как собрать установщик', 1)[0]
    (package / 'INSTALLATION.md').write_text(guide.rstrip() + '\n', encoding='utf-8')
    backend_metadata = build_backend(work, package)
    run([str(compiler), '/nologo', '/target:library', '/platform:x64', '/optimize+', '/debug-',
         '/out:' + str(package / 'backend/MtpCopy.dll'), str(ROOT / 'cartoon_downloader/mtp_copy.cs')])
    # The development manifest also covers python.exe, which is not shipped.
    component_lines = (ROOT / 'BUNDLED_COMPONENTS.sha256').read_text(encoding='utf-8').splitlines()
    (package / 'BUNDLED_COMPONENTS.sha256').write_text(
        '\n'.join(line for line in component_lines if line.split(maxsplit=1)[1].startswith('tools/'))
        + '\n' + backend_metadata['backend_sha256'] + '  backend/CartoonDownloader.Backend.exe\n', encoding='utf-8')
    sources = work / 'launcher-source'
    sources.mkdir()
    file_version = __version__ + '.0'
    launcher = sources / 'Launcher.cs'
    launcher.write_text((ROOT / 'packaging/Launcher.cs').read_text(encoding='utf-8')
                        .replace('@@FILE_VERSION@@', file_version), encoding='utf-8')
    desktop = sources / 'DesktopWindow.cs'
    shutil.copyfile(ROOT / 'packaging/DesktopWindow.cs', desktop)
    shutil.copyfile(ROOT / 'packaging/app.manifest', sources / 'app.manifest')
    for name in ('Microsoft.Web.WebView2.Core.dll', 'Microsoft.Web.WebView2.WinForms.dll', 'WebView2Loader.dll'):
        shutil.copyfile(ROOT / 'tools/webview2' / name, package / name)
    shutil.copyfile(ROOT / 'packaging/make_icon.ps1', sources / 'make_icon.ps1')
    icon = package / 'CartoonDownloader.ico'
    run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
         '-File', str(ROOT / 'packaging/make_icon.ps1'), '-Source',
         str(ROOT / 'static/assets/cartoon-logo.png'), '-Output', str(icon)])
    executable = package / 'CartoonDownloader.exe'
    run([str(compiler), '/nologo', '/target:winexe', '/platform:x64', '/optimize+', '/debug-',
         '/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll',
         '/reference:System.Web.Extensions.dll',
         '/reference:' + str(package / 'Microsoft.Web.WebView2.Core.dll'),
         '/reference:' + str(package / 'Microsoft.Web.WebView2.WinForms.dll'),
         '/win32icon:' + str(icon), '/win32manifest:' + str(sources / 'app.manifest'),
         '/out:' + str(executable), str(launcher), str(desktop)])
    manifest = {
        'product': 'Cartoon Downloader Desktop', 'version': __version__,
        'architecture': 'windows-x64', 'format': 'portable-folder',
        'entrypoint': executable.name, 'runtime': 'Nuitka standalone native backend with bundled CPython libraries',
        'compiled_backend': backend_metadata,
        'launcher_framework': '.NET Framework 4.6.2+ (Windows)',
        'ui': 'native WinForms window with bundled WebView2 Fixed Version',
        'webview2': json.loads((ROOT / 'tools/webview2/DEPENDENCY.json').read_text(encoding='utf-8')),
        'deno': json.loads((ROOT / 'tools/deno/DEPENDENCY.json').read_text(encoding='utf-8')),
        'ffmpeg': json.loads((ROOT / 'tools/ffmpeg/DEPENDENCY.json').read_text(encoding='utf-8')),
        'excluded_debug_extensions': ['.pdb'],
        'excluded_sources': ['Python', 'SQL migrations', 'C#', 'packaging scripts', 'HTML/CSS/JS/SVG files'],
        'compiler_sha256': digest(compiler),
        'launcher_sha256': digest(executable),
        'source_version': file_version,
        'build_recipe': 'packaging/build_windows.py',
    }
    (package / 'RELEASE.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    errors = verify(package)
    if errors:
        raise RuntimeError('\n'.join(errors))
    # Catch resource-root and missing runtime DLL failures before publication,
    # without creating a database, profile or other user data in the package.
    run([sys.executable, '-E', '-s', '-B', str(ROOT / 'verify_package.py'), '--package', str(package)])
    files = sorted(path for path in package.rglob('*') if path.is_file())
    checksums = ''.join(f'{digest(path)}  {path.relative_to(package).as_posix()}\n' for path in files)
    (package / 'PACKAGE.sha256').write_text(checksums, encoding='utf-8')
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        check_previous_build()
        archive = Path(tempfile.mkdtemp(prefix='previous-release-', dir=ROOT / 'build'))
        # Both absolute endpoints are contained in this workspace, and no
        # recursive deletion is performed. Keep the previous artifact intact.
        if not destination.resolve().is_relative_to(distribution) or not archive.resolve().is_relative_to(ROOT / 'build'):
            raise RuntimeError('Unsafe package archive path')
        destination.rename(archive / destination.name)
        print('Previous build preserved:', archive, flush=True)
    package.rename(destination)
    # Python 3.13 creates mkdtemp directories with an owner-only Windows ACL.
    # Moving that staging tree retains its ACL; inherit the destination's normal
    # workspace permissions so the user's account can run the published package.
    run(['icacls.exe', str(destination), '/reset', '/T', '/C', '/Q'])
    # Required for unpackaged Fixed Version renderers on Windows 10, v120+.
    run(['icacls.exe', str(destination / 'tools/webview2/runtime'), '/grant',
         '*S-1-15-2-2:(OI)(CI)(RX)', '*S-1-15-2-1:(OI)(CI)(RX)', '/T', '/C', '/Q'])
    # Keep compiler sources, logs and reports privately under ignored build/.
    print(json.dumps({'package': str(destination), 'version': __version__, 'files': len(files) + 1,
                      'launcher_sha256': manifest['launcher_sha256']}, ensure_ascii=False), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
