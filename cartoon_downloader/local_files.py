"""Job-owned staging, local promotion and receipts; no job state or SQL."""
from __future__ import annotations

import json
import os
import re
import shutil
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PreparedLocalFile:
    staging: Path
    destination: Path


class LocalFiles:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.temp = self.root / 'temp'

    def job_directory(self, job_id: int) -> Path:
        if type(job_id) is not int or job_id <= 0:
            raise ValueError('Invalid job ID for staging')
        path = self.temp / f'job-{job_id}'
        if (self.temp.is_symlink() or self.temp.is_junction()
                or path.is_symlink() or path.is_junction()
                or path.resolve().parent != self.temp):
            raise ValueError('Unsafe job staging directory')
        return path

    def cleanup(self, job_id: int) -> None:
        # Resolve and check the exact job directory before every recursive
        # operation. shutil.rmtree does not traverse Windows junction targets.
        shutil.rmtree(self.job_directory(job_id), ignore_errors=True)

    def prepare_download(self, job_id: int) -> Path:
        path = self.job_directory(job_id)
        self.cleanup(job_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def find_media(folder: Path, youtube_id: str) -> Path | None:
        candidates = [path for path in Path(folder).glob('*')
                      if path.is_file() and f'[{youtube_id}]' in path.name
                      and not path.name.endswith(('.part', '.ytdl', '.cdtmp', '.tmp'))]
        return max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None

    @contextmanager
    def prepare_local(self, job_id: int, source: Path, configured_folder: str,
                      check_cancel: Callable[[], None]) -> Iterator[PreparedLocalFile]:
        directory = Path(configured_folder or 'downloads').expanduser()
        directory = directory if directory.is_absolute() else self.root / directory
        resolved = directory.resolve()
        if resolved.is_relative_to(self.temp):
            relative = resolved.relative_to(self.temp)
            if relative.parts and re.fullmatch(r'job-[0-9]+', relative.parts[0]):
                raise ValueError('Local downloads folder cannot be inside job staging')
        directory.mkdir(parents=True, exist_ok=True)
        prepared = PreparedLocalFile(
            directory / f'.{source.name}.job-{job_id}.cdtmp', directory / source.name,
        )
        try:
            with source.open('rb') as src, prepared.staging.open('wb') as dst:
                while True:
                    check_cancel()
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    dst.write(chunk)
            shutil.copystat(source, prepared.staging)
            check_cancel()
            yield prepared
        finally:
            prepared.staging.unlink(missing_ok=True)

    @staticmethod
    def promote(prepared: PreparedLocalFile) -> Path:
        os.replace(prepared.staging, prepared.destination)
        return prepared.destination

    def receipt_path(self, job_id: int) -> Path:
        return self.job_directory(job_id) / 'finalized.json'

    def record_finalized(self, job_id: int, target: Path, actual_quality: int | None) -> None:
        stat = target.stat()
        receipt = {'job_id': job_id, 'path': str(target.resolve()), 'size': stat.st_size,
                   'mtime_ns': stat.st_mtime_ns, 'ctime_ns': stat.st_ctime_ns,
                   'actual_quality': actual_quality}
        path = self.receipt_path(job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.tmp')
        with temporary.open('w', encoding='utf-8') as stream:
            json.dump(receipt, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)

    def finalized_receipt(self, job_id: int) -> dict | None:
        receipt = json.loads(self.receipt_path(job_id).read_text(encoding='utf-8'))
        target = Path(receipt['path'])
        stat = target.stat()
        if (receipt['job_id'] != job_id or not target.is_file()
                or stat.st_size != receipt['size'] or stat.st_mtime_ns != receipt['mtime_ns']
                or stat.st_ctime_ns != receipt['ctime_ns']):
            return None
        return receipt
