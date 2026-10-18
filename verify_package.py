"""Offline portable-package verification; never opens the user's database."""

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

from cartoon_downloader.tooling import Tooling


def verify(root: Path) -> list[str]:
    errors = []
    release = root / 'RELEASE.json'
    compiled = release.is_file() and bool(json.loads(release.read_text(encoding='utf-8')).get('compiled_backend'))
    required = [
        'START_WINDOWS.bat', 'app.py', 'diagnostics.py',
        'runtime/python/python.exe', 'runtime/python/python313.dll',
        'runtime/python/Lib/sqlite3/__init__.py',
        'cartoon_downloader/mtp_copy.cs',
        'cartoon_downloader/catalog.py', 'cartoon_downloader/runtime.py',
        'cartoon_downloader/logs.py', 'cartoon_downloader/retained_sources.py',
        'cartoon_downloader/download_runner.py', 'cartoon_downloader/local_files.py',
        'cartoon_downloader/device_transfer.py',
        'cartoon_downloader/paths.py',
        'static/index.html', 'static/app.js', 'static/app.css',
        'static/assets/hero_2k.png', 'static/assets/cartoon-logo.png',
        'migrations/001_initial.sql', 'migrations/002_queue_recovery.sql',
        'migrations/003_video_availability.sql', 'migrations/004_job_logging.sql',
        'migrations/005_download_quality.sql', 'migrations/006_actual_quality.sql',
        'migrations/007_runtime_revisions.sql',
        'THIRD_PARTY_NOTICES.md', 'BUNDLED_COMPONENTS.sha256',
        'tools/yt-dlp/THIRD_PARTY_LICENSES.txt',
        'tools/ffmpeg/LICENSE.txt', 'tools/deno/LICENSE.txt',
        'tools/ffmpeg/DEPENDENCY.json', 'tools/deno/DEPENDENCY.json',
        'tools/webview2/DEPENDENCY.json', 'tools/webview2/FILES.sha256',
        'tools/webview2/LICENSE.txt', 'tools/webview2/runtime/msedgewebview2.exe',
        'tools/webview2/RUNTIME-LICENSE.txt', 'tools/webview2/RUNTIME-LICENSE.html',
        'tools/webview2/Microsoft.Web.WebView2.Core.dll',
        'tools/webview2/Microsoft.Web.WebView2.WinForms.dll', 'tools/webview2/WebView2Loader.dll',
    ]
    if compiled:
        required = [name for name in required
                    if name not in {'START_WINDOWS.bat', 'app.py', 'diagnostics.py'}
                    and not name.startswith(('cartoon_downloader/', 'migrations/', 'runtime/python/Lib/'))
                    and name not in {'runtime/python/python.exe', 'runtime/python/python313.dll'}
                    and not (name.startswith('static/') and Path(name).suffix in {'.js', '.css', '.html', '.svg'})]
        required.extend(['CartoonDownloader.exe', 'backend/CartoonDownloader.Backend.exe',
                         'backend/python313.dll', 'backend/MtpCopy.dll',
                         'runtime/nuitka/LICENSE.txt', 'runtime/nuitka/LICENSE-RUNTIME.txt'])
        for name in ('cartoon_downloader', 'migrations', 'packaging', 'launcher-source',
                     'app.py', 'diagnostics.py', 'verify_package.py', 'START_WINDOWS.bat',
                     'runtime/python/python.exe'):
            if (root / name).exists():
                errors.append(f'Developer source/runtime in compiled release: {name}')
        for folder in (root / 'backend', root / 'static'):
            for path in folder.rglob('*'):
                if path.is_file() and path.suffix.lower() in {
                    '.py', '.pyw', '.pyc', '.pyo', '.sql', '.cs', '.ps1', '.pdb',
                    '.c', '.h', '.lib', '.html', '.js', '.css', '.svg',
                }:
                    errors.append(f'Source/debug file in compiled release: {path.relative_to(root)}')
    required.extend(str(path.relative_to(root)) for path in Tooling(root).required_files().values())
    for name in required:
        if not (root / name).is_file():
            errors.append(f'Missing package file: {name}')
    migrations = sorted((root / 'migrations').glob('*.sql'))
    if not compiled and (not migrations or migrations[0].name != '001_initial.sql'):
        errors.append('Initial database migration missing')
    sources = [] if compiled else [root / 'app.py', root / 'diagnostics.py', *(root / 'cartoon_downloader').glob('*.py')]
    for path in sources:
        try:
            compile(path.read_text(encoding='utf-8'), str(path), 'exec')
        except (OSError, SyntaxError) as exc:
            errors.append(f'Invalid Python source: {exc}')
    # Native ES modules are part of the package, without a build step.
    for path in (root / 'static').rglob('*.js'):
        for relative in re.findall(r'(?:from\s*|import\s*)[\'"](\.[^\'"]+)[\'"]', path.read_text(encoding='utf-8')):
            target = (path.parent / relative).resolve()
            if not target.is_relative_to((root / 'static').resolve()) or not target.is_file():
                errors.append(f'Missing frontend module: {path.name} -> {relative}')
    for manifest in (root / 'BUNDLED_COMPONENTS.sha256', root / 'tools/webview2/FILES.sha256'):
        if not manifest.is_file():
            continue
        base = root if manifest.name == 'BUNDLED_COMPONENTS.sha256' else manifest.parent
        for line in manifest.read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            expected, name = line.split(maxsplit=1)
            path = (base / name).resolve()
            if not path.is_relative_to(base.resolve()) or not path.is_file():
                errors.append(f'Missing checksum target: {name}')
                continue
            with path.open('rb') as stream:
                actual = hashlib.file_digest(stream, 'sha256').hexdigest()
            if actual != expected:
                errors.append(f'Checksum mismatch: {name}')
    return errors


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, default=Path(__file__).resolve().parent)
    root = parser.parse_args().package.resolve()
    errors = verify(root)
    if not errors:
        tooling = Tooling(root)
        commands = {
            'Python': [str(root / 'runtime/python/python.exe'), '-E', '-s', '-B', '-c',
                       'import sqlite3,ssl,ctypes,http.server,unittest; import sys; print(sys.version); assert sys.version_info[:2] == (3,13)'],
            'yt-dlp': [str(tooling.ytdlp), '--version'],
            'Deno': [str(tooling.deno), '--version'],
            'FFmpeg': [str(tooling.ffmpeg), '-version'],
            'ffprobe': [str(tooling.ffprobe), '-version'],
        }
        if (root / 'backend/CartoonDownloader.Backend.exe').is_file():
            del commands['Python']
            commands['Backend'] = [str(root / 'backend/CartoonDownloader.Backend.exe'), '--diagnostics',
                                   '--data-dir', str(root / 'nonexistent-diagnostic-data')]
        for name, command in commands.items():
            try:
                result = subprocess.run(command, capture_output=True, text=True,
                                        encoding='utf-8', errors='replace', timeout=20,
                                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                if result.returncode:
                    errors.append(f'{name} cannot start: {result.stderr[-600:]}')
                else:
                    if name == 'Backend':
                        try:
                            details, _ = json.JSONDecoder().raw_decode(result.stdout[result.stdout.index('{'):])
                            for component in ('engine', 'yt-dlp', 'deno', 'ffmpeg', 'ffprobe', 'python'):
                                if not details[component]['ok']:
                                    errors.append(f'Backend cannot locate {component}: {details[component]["path"]}')
                        except (ValueError, KeyError, TypeError) as exc:
                            errors.append(f'Invalid backend diagnostics: {exc}')
                    print(name + ': ' + result.stdout.splitlines()[0])
            except (OSError, subprocess.TimeoutExpired) as exc:
                errors.append(f'{name} cannot start: {exc}')
    for error in errors:
        print('ERROR:', error, file=sys.stderr)
    if not errors:
        print('Package: OK (offline; files, code/resources, hashes, tool startup)')
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
