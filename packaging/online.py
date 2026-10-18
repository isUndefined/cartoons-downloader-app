"""Pinned online dependency layout and Inno Setup input generation."""
from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse


def safe_relative(value: str) -> str:
    path = PurePosixPath(value)
    if (not value or path.is_absolute() or '..' in path.parts
            or any(c in value for c in ('\\', ':', '"', "'", ';', '{', '}', '\r', '\n'))):
        raise ValueError(f'Unsafe dependency path: {value}')
    return path.as_posix()


def load_components(path: Path) -> list[dict]:
    document = json.loads(path.read_text(encoding='utf-8'))
    if document.get('schema') != 1 or document.get('architecture') != 'windows-x64':
        raise ValueError('Unsupported online dependency manifest')
    components = document['components']
    ids = set()
    roots = []
    for component in components:
        identifier = component['id']
        if not re.fullmatch(r'[a-z][a-z0-9-]*', identifier) or identifier in ids:
            raise ValueError('Invalid or repeated online dependency ID')
        ids.add(identifier)
        url = urlparse(component['url'])
        if url.scheme != 'https' or not url.hostname or url.username or url.password or url.fragment:
            raise ValueError('Online dependencies require HTTPS URLs without credentials')
        if not re.fullmatch('[0-9a-f]{64}', component['sha256']):
            raise ValueError('Online dependencies require pinned SHA256 hashes')
        if component['format'] not in {'file', 'zip', 'cab'} or component['download_bytes'] <= 0:
            raise ValueError('Invalid dependency archive format or size')
        package_root = safe_relative(component['package_root'])
        if any(package_root == other or package_root.startswith(other + '/')
               or other.startswith(package_root + '/') for other in roots):
            raise ValueError('Overlapping online dependency roots')
        roots.append(package_root)
        if component['archive_prefix']:
            safe_relative(component['archive_prefix'])
        for name in component.get('files', []):
            safe_relative(name)
        if component['format'] == 'file' and len(component.get('files', [])) != 1:
            raise ValueError('A raw download must map exactly one file')
    if not components:
        raise ValueError('No online dependencies configured')
    return components


def archive_name(component: dict) -> str:
    suffix = component['format'] if component['format'] != 'file' else 'exe'
    return f'online-{component["id"]}.{suffix}'


def external_files(files: list[Path], components: list[dict]) -> dict[str, tuple[dict, str]]:
    """Map exact package entries to their verified download staging paths."""
    result = {}
    for component in components:
        root = component['package_root'] + '/'
        selected = set(component.get('files', []))
        matches = []
        for relative in files:
            name = relative.as_posix()
            if not name.startswith(root):
                continue
            tail = name.removeprefix(root)
            if selected and tail not in selected:
                continue
            safe_relative(tail)
            if component['format'] == 'file':
                staged = archive_name(component)
            else:
                prefix = component['archive_prefix']
                staged = '/'.join(part for part in ('online', component['id'], prefix, tail) if part)
            result[name] = (component, staged.replace('/', '\\'))
            matches.append(tail)
        if not matches or selected and set(matches) != selected:
            raise ValueError('Package does not match online component: ' + component['id'])
    return result


def write_online_inputs(work: Path, package: Path, files: list[Path], components: list[dict], digest) -> dict:
    mapping = external_files(files, components)
    verification = []
    for name, (_component, staged) in mapping.items():
        verification.append(f'{digest(package / name)}  {staged}\n')
    (work / 'OnlineFiles.sha256').write_text(''.join(verification), encoding='utf-8')
    downloads = []
    extractions = []
    for component in components:
        downloads.append("  DownloadPage.Add('%s', '%s', '%s');\n" % (
            component['url'].replace("'", "''"), archive_name(component), component['sha256']))
        if component['format'] != 'file':
            extractions.append("  ExtractDependency('%s', '%s');\n" % (archive_name(component), component['id']))
    (work / 'OnlineDownloads.iss').write_text(''.join(downloads), encoding='utf-8-sig')
    (work / 'OnlineExtraction.iss').write_text(''.join(extractions), encoding='utf-8-sig')
    return {'mapping': mapping, 'download_bytes': sum(c['download_bytes'] for c in components),
            'external_bytes': sum((package / name).stat().st_size for name in mapping)}
