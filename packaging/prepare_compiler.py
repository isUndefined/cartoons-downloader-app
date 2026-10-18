"""One-time preparation of the pinned compiler under build/ (never installed globally)."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tarfile
import urllib.request
import zipfile
from pathlib import Path

from compiled_backend import ROOT, TOOLCHAIN, PYTHON, ZIG, check_toolchain, digest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline', action='store_true', help='Use only previously downloaded, verified archives')
    args = parser.parse_args()
    lock_path = ROOT / 'packaging/compiler-toolchain.json'
    lock = json.loads(lock_path.read_text(encoding='utf-8'))
    TOOLCHAIN.mkdir(parents=True, exist_ok=True)
    archives = TOOLCHAIN / 'archives'
    archives.mkdir(exist_ok=True)
    inputs = [lock['python'], *lock['packages'], lock['dependency_walker']]
    for item in inputs:
        archive = archives / item['filename']
        if not archive.is_file():
            if args.offline:
                raise RuntimeError(f'Missing pinned archive: {archive}')
            print('Downloading:', item['filename'], flush=True)
            temporary = archive.with_suffix(archive.suffix + '.part')
            with urllib.request.urlopen(item['url'], timeout=120) as response, temporary.open('wb') as out:
                shutil.copyfileobj(response, out)
            if digest(temporary) != item['sha256']:
                raise RuntimeError(f'Archive SHA256 mismatch: {item["filename"]}')
            temporary.replace(archive)
        if digest(archive) != item['sha256']:
            raise RuntimeError(f'Archive SHA256 mismatch: {item["filename"]}')
    if not PYTHON.exists():
        with tarfile.open(archives / lock['python']['filename']) as archive:
            archive.extractall(TOOLCHAIN, filter='data')
    nuitka = next(item for item in lock['packages'] if item['name'] == 'Nuitka')
    compiler_source = TOOLCHAIN / f'nuitka-{nuitka["version"]}'
    if not compiler_source.exists():
        with tarfile.open(archives / nuitka['filename']) as archive:
            archive.extractall(TOOLCHAIN, filter='data')
    # No dependency resolver or build isolation may download an unpinned input.
    command = [str(PYTHON), '-I', '-B', '-m', 'pip', 'install', '--disable-pip-version-check',
               '--no-cache-dir', '--no-index', '--no-deps', '--no-build-isolation']
    wheels = [str(archives / item['filename']) for item in lock['packages'] if item is not nuitka]
    subprocess.run(command + wheels, check=True)
    probe = subprocess.run([str(PYTHON), '-I', '-B', '-c',
                            'import importlib.metadata; print(importlib.metadata.version("Nuitka"))'],
                           capture_output=True, text=True)
    if probe.returncode or probe.stdout.strip() != nuitka['version']:
        subprocess.run(command + [str(archives / nuitka['filename'])], check=True)
    depends = TOOLCHAIN / 'cache/downloads/depends/x86_64'
    depends.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archives / lock['dependency_walker']['filename']) as archive:
        archive.extractall(depends)
    binaries = [PYTHON, PYTHON.with_name('python313.dll'), ZIG, depends / 'depends.exe', depends / 'depends.dll']
    inventory = {'lock_sha256': digest(lock_path),
                 'binaries': {path.relative_to(TOOLCHAIN).as_posix(): digest(path) for path in binaries}}
    (TOOLCHAIN / 'PREPARED.json').write_text(json.dumps(inventory, indent=2) + '\n', encoding='utf-8')
    check_toolchain()
    print('Build-only compiler: ready. Normal builds do not download dependencies.', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
