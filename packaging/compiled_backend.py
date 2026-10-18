"""Build the application as native code with a pinned, build-only toolchain."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLCHAIN = ROOT / 'build/compiler-tools'
PYTHON = TOOLCHAIN / 'python/python.exe'
ZIG = TOOLCHAIN / 'python/Lib/site-packages/ziglang/zig.exe'
TEXT_ASSETS = {'.html', '.css', '.js', '.svg'}
FORBIDDEN = {'.py', '.pyw', '.pyc', '.pyo', '.sql', '.cs', '.ps1', '.pdb', '.c', '.h', '.lib'}


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def check_toolchain() -> dict:
    lock = json.loads((ROOT / 'packaging/compiler-toolchain.json').read_text(encoding='utf-8'))
    for path in (PYTHON, ZIG, TOOLCHAIN / 'python/include/Python.h', TOOLCHAIN / 'python/libs/python313.lib'):
        if not path.is_file():
            raise RuntimeError(f'Missing compiler component: {path}. Run packaging/prepare_compiler.py first.')
    probe = subprocess.run([str(PYTHON), '-I', '-B', '-c',
                            'import importlib.metadata,json,sys; '
                            'print(json.dumps({"python":sys.version.split()[0],'
                            '"packages":{n:importlib.metadata.version(n) for n in '
                            '["Nuitka","ordered-set","ziglang","setuptools","wheel"]}}))'],
                           check=True, capture_output=True, text=True, timeout=30)
    actual = json.loads(probe.stdout)
    if actual['python'] != lock['python']['version']:
        raise RuntimeError('Build Python differs from compiler-toolchain.json')
    for item in lock['packages']:
        if actual['packages'].get(item['name']) != item['version']:
            raise RuntimeError(f'Wrong compiler dependency: {item["name"]}')
    prepared = TOOLCHAIN / 'PREPARED.json'
    if not prepared.is_file():
        raise RuntimeError('Compiler inventory missing. Run packaging/prepare_compiler.py first.')
    inventory = json.loads(prepared.read_text(encoding='utf-8'))
    for relative, expected in inventory['binaries'].items():
        path = TOOLCHAIN / relative
        if not path.is_file() or digest(path) != expected:
            raise RuntimeError(f'Compiler binary changed: {relative}')
    if inventory['lock_sha256'] != digest(ROOT / 'packaging/compiler-toolchain.json'):
        raise RuntimeError('Compiler lock changed. Prepare the toolchain again.')
    return lock


def build_backend(work: Path, package: Path) -> dict:
    lock = check_toolchain()
    source = work / 'source'
    source.mkdir()
    # Compile a private snapshot. Generated modules never touch the source tree.
    source_package = source / 'cartoon_downloader'
    source_package.mkdir()
    for path in sorted((ROOT / 'cartoon_downloader').glob('*.py')):
        if path.is_symlink():
            raise RuntimeError(f'Redirected source input: {path}')
        shutil.copyfile(path, source_package / path.name)
    for name in ('app.py', 'diagnostics.py'):
        shutil.copyfile(ROOT / name, source / name)
    shutil.copyfile(ROOT / 'packaging/backend_main.py', source / 'backend_main.py')
    migrations = tuple((path.name, path.read_text(encoding='utf-8'))
                       for path in sorted((ROOT / 'migrations').glob('*.sql')))
    static = {path.relative_to(ROOT / 'static').as_posix(): path.read_bytes()
              for path in sorted((ROOT / 'static').rglob('*'))
              if path.is_file() and path.suffix.lower() in TEXT_ASSETS}
    (source / 'cartoon_downloader/_embedded.py').write_text(
        'MIGRATIONS = ' + repr(migrations) + '\nSTATIC = ' + repr(static) + '\n', encoding='utf-8')
    output = work / 'native'
    report = work / 'compilation-report.xml'
    environment = os.environ.copy()
    environment['PATH'] = str(ZIG.parent) + os.pathsep + environment.get('PATH', '')
    environment['CC'] = str(ZIG)
    environment['NUITKA_CACHE_DIR'] = str(TOOLCHAIN / 'cache')
    # Zig's cache entries can have owner-only ACLs. A build started under a
    # different Windows account must not reuse an unreadable shared cache.
    environment['NUITKA_CACHE_DIR_ZIG'] = str(work / 'zig-cache')
    environment.pop('ZIG_GLOBAL_CACHE_DIR', None)
    environment.pop('ZIG_LOCAL_CACHE_DIR', None)
    command = [str(PYTHON), '-I', '-B', '-m', 'nuitka', '--mode=standalone', '--zig',
               '--python-flag=isolated,no_site,dont_write_bytecode,no_docstrings',
               '--deployment', '--lto=no', '--jobs=4', '--no-progressbar',
               '--include-module=cartoon_downloader._embedded',
               '--nofollow-import-to=unittest,tkinter,pydoc,doctest,ensurepip,pip',
               '--output-filename=CartoonDownloader.Backend.exe', '--output-dir=' + str(output),
               '--report=' + str(report), str(source / 'backend_main.py')]
    print('Compiling Python backend (Nuitka + Zig); details:', work / 'compile.log', flush=True)
    with (work / 'compile.log').open('w', encoding='utf-8') as log:
        result = subprocess.run(command, cwd=source, env=environment, stdout=log,
                                stderr=subprocess.STDOUT, timeout=3600,
                                creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError((work / 'compile.log').read_text(encoding='utf-8', errors='replace')[-6000:])
    modules = {element.get('name'): element.get('kind')
               for element in ET.parse(report).getroot().findall('module')}
    expected = {'app', 'diagnostics', 'cartoon_downloader', 'cartoon_downloader._embedded'}
    expected.update('cartoon_downloader.' + path.stem for path in source_package.glob('*.py')
                    if path.name != '__init__.py')
    for name in expected:
        if modules.get(name) not in {'CompiledPythonModule', 'CompiledPythonPackage'}:
            raise RuntimeError(f'Application module was not compiled to native code: {name}')
    built = output / 'backend_main.dist'
    if not (built / 'CartoonDownloader.Backend.exe').is_file():
        raise RuntimeError('Compiler did not produce the standalone backend')
    for path in built.rglob('*'):
        if path.is_file() and path.suffix.lower() in FORBIDDEN:
            raise RuntimeError(f'Unexpected source/debug file in compiled backend: {path.name}')
    shutil.copytree(built, package / 'backend')
    licenses = package / 'runtime/nuitka'
    licenses.mkdir(parents=True)
    # Preserve the exact runtime license and additional permission from the
    # pinned compiler source, rather than substituting a different version.
    compiler_source = TOOLCHAIN / ('nuitka-' + next(item['version'] for item in lock['packages'] if item['name'] == 'Nuitka'))
    for name in ('LICENSE.txt', 'LICENSE-RUNTIME.txt'):
        shutil.copyfile(compiler_source / name, licenses / name)
    zig_licenses = package / 'runtime/zig'
    zig_licenses.mkdir()
    shutil.copyfile(ZIG.with_name('LICENSE'), zig_licenses / 'LICENSE.txt')
    return {'compiler': lock, 'backend_sha256': digest(package / 'backend/CartoonDownloader.Backend.exe'),
            'embedded_migrations': [name for name, _ in migrations],
            'embedded_static_files': sorted(static), 'report': str(report.relative_to(ROOT))}
