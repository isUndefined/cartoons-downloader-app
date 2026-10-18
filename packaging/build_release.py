"""One-command checks, application build and installer build for BUILD_SETUP.bat."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cartoon_downloader import __version__
from build_setup import check_previous_setup, digest
from online import load_components


def run_steps(steps: list[tuple[str, list[str]]], root: Path) -> None:
    for index, (label, command) in enumerate(steps, 1):
        print(f'\n[{index}/{len(steps)}] {label}', flush=True)
        # Keep output visible. A failed check must prevent all following steps.
        subprocess.run(command, cwd=root, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-only', action='store_true', help='Check build prerequisites without building or moving files')
    parser.add_argument('--no-pause', action='store_true', help='Used by BUILD_SETUP.bat when this is its first argument')
    parser.add_argument('--offline', action='store_true', help='Bundle tools instead of downloading them at installation')
    args = parser.parse_args()
    try:
        if not re.fullmatch(r'\d+\.\d+\.\d+', __version__):
            raise RuntimeError('Use a three-part version in cartoon_downloader/__init__.py, for example 0.30.1')
        python = ROOT / 'runtime/python/python.exe'
        deno = ROOT / 'tools/deno/deno.exe'
        compiler = ROOT / 'build/installer-tools/inno-7.1.0/ISCC.exe'
        for path in (python, deno, compiler, ROOT / 'packaging/build_windows.py', ROOT / 'packaging/build_setup.py',
                     ROOT / 'packaging/online.iss', ROOT / 'packaging/online-components.json'):
            if not path.is_file():
                raise RuntimeError(f'Missing build component: {path}')
        lock = json.loads((ROOT / 'packaging/installer-toolchain.json').read_text(encoding='utf-8'))
        if digest(compiler) != lock['compiler_sha256']:
            raise RuntimeError('The Inno Setup compiler differs from packaging/installer-toolchain.json')
        if not args.offline:
            load_components(ROOT / 'packaging/online-components.json')
        package = ROOT / 'dist' / f'CartoonDownloader-{__version__}'
        variant = 'Setup' if args.offline else 'Online-Setup'
        filename = 'CartoonDownloader-Setup.exe' if args.offline else 'CartoonDownloader-Online-Setup.exe'
        output = ROOT / 'dist' / f'CartoonDownloader-{__version__}-{variant}'
        if package.exists():
            if package.is_symlink() or package.is_junction():
                raise RuntimeError('The existing package directory is redirected')
            metadata = json.loads((package / 'RELEASE.json').read_text(encoding='utf-8'))
            if metadata.get('product') != 'Cartoon Downloader Desktop':
                raise RuntimeError('The existing output is not an application build')
            if any((package / name).exists() for name in ('data', 'logs', 'temp', 'downloads', 'installed.marker')):
                raise RuntimeError('The existing package contains user data. Increase __version__ in cartoon_downloader/__init__.py; keep the old folder.')
        if output.exists():
            check_previous_setup(output, online=not args.offline)
        print(f'Cartoon Downloader {__version__}\nProject: {ROOT}\nInstaller: {variant}', flush=True)
        if args.check_only:
            print('Build prerequisites: OK. No builds or files were changed.', flush=True)
            return 0
        py = [str(python), '-E', '-s', '-B', '-u', '-X', 'utf8']
        run_steps([
            ('Verify application files and bundled tools', py + ['verify_package.py']),
            ('Frontend formatting', [str(deno), 'fmt', '--check', 'static']),
            ('Build application', py + ['packaging/build_windows.py', '--archive-existing']),
            ('Build installer', py + ['packaging/build_setup.py', '--package', str(package), '--archive-existing']
             + ([] if args.offline else ['--online'])),
        ], ROOT)
        print(f'\nREADY: {output / filename}', flush=True)
        print('Previous clean builds were preserved under build/.', flush=True)
        return 0
    except subprocess.CalledProcessError as error:
        print(f'\nERROR: Step failed with exit code {error.returncode}. Following steps were not run.', file=sys.stderr, flush=True)
        return error.returncode if 0 < error.returncode < 256 else 1
    except (OSError, ValueError, RuntimeError) as error:
        print(f'\nERROR: {error}', file=sys.stderr, flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
