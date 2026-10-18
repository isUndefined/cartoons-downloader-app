"""Bounded UTF-8 logs. Retention applies only to application-owned log names."""
from __future__ import annotations

import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path


class LogStore:
    MAX_BYTES = 2 * 1024 * 1024
    BACKUPS = 2
    RETENTION_DAYS = 30
    TAIL_BYTES = 256 * 1024

    def __init__(self, root: Path, db, *, max_bytes=MAX_BYTES):
        self.root = Path(root).resolve() / 'logs'
        self.db = db
        self.max_bytes = max_bytes
        self.lock = threading.RLock()
        self.next_prune = 0.0

    def _safe(self, path: Path) -> bool:
        # Refuse symlinks and Windows junctions, including parent directories.
        candidate = Path(path).absolute()
        if not candidate.is_relative_to(self.root):
            return False
        for item in (candidate, *candidate.parents):
            if item.is_symlink() or item.is_junction():
                return False
            if item == self.root:
                return candidate.resolve().is_relative_to(self.root)
        return False

    def prune(self, protected: Path | None = None) -> list[str]:
        """Best-effort expiry; never prune active jobs or unknown files."""
        errors = []
        with self.lock:
            cutoff = time.time() - self.RETENTION_DAYS * 86400
            with self.db.connect() as con:
                active = {row[0] for row in con.execute(
                    "SELECT id FROM download_jobs WHERE status IN "
                    "('queued','downloading','processing','transferring','verifying')"
                )}
            for directory, pattern in [
                (self.root, r'discovery\.log(?:\.[12])?'),
                (self.root / 'jobs', r'job-([1-9][0-9]*)\.log(?:\.[12])?'),
            ]:
                if not self._safe(directory) or not directory.is_dir():
                    continue
                for path in directory.iterdir():
                    match = re.fullmatch(pattern, path.name)
                    if not match or not self._safe(path) or not path.is_file():
                        continue
                    if match.lastindex and int(match[1]) in active:
                        continue
                    if protected and path == protected:
                        continue
                    try:
                        if path.stat().st_mtime < cutoff:
                            path.unlink()
                    except OSError as exc:
                        errors.append(f'{path.name}: {exc}')
            self.next_prune = time.monotonic() + 3600
        return errors

    def append(self, path: Path, text: str):
        stamp = datetime.now(timezone.utc).isoformat(timespec='seconds')
        data = ''.join(f'[{stamp}] {line}\n' for line in str(text).splitlines() or ['']).encode('utf-8', errors='replace')
        # A single unusually long subprocess line must not bypass the size cap.
        data = data[-self.max_bytes:].decode('utf-8', errors='ignore').encode('utf-8')
        with self.lock:
            if not self._safe(path):
                raise ValueError('Unsafe log path')
            if time.monotonic() >= self.next_prune:
                self.prune(protected=path)
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and path.stat().st_size + len(data) > self.max_bytes:
                for number in range(self.BACKUPS, 0, -1):
                    destination = Path(f'{path}.{number}')
                    source = path if number == 1 else Path(f'{path}.{number-1}')
                    if not self._safe(destination) or not self._safe(source):
                        raise ValueError('Unsafe rotated log path')
                    if number == self.BACKUPS:
                        destination.unlink(missing_ok=True)
                    if source.exists():
                        self._trim_legacy_file(source)
                        source.replace(destination)
            with path.open('ab') as stream:
                stream.write(data)

    def _trim_legacy_file(self, path: Path):
        if path.stat().st_size <= self.max_bytes:
            return
        # Bound logs left by older builds without reading them in full.
        with path.open('rb') as stream:
            stream.seek(-self.max_bytes, 2)
            data = stream.read(self.max_bytes)
        data = data.decode('utf-8', errors='ignore').encode('utf-8')
        with path.open('wb') as stream:
            stream.write(data)

    def tail(self, path: Path, max_lines: int = 160) -> str:
        with self.lock:
            pieces = []
            remaining = self.TAIL_BYTES
            for number in range(self.BACKUPS + 1):
                source = path if number == 0 else Path(f'{path}.{number}')
                if not self._safe(source) or not source.is_file():
                    continue
                with source.open('rb') as stream:
                    size = stream.seek(0, 2)
                    start = max(0, size - remaining)
                    stream.seek(start)
                    piece = stream.read(remaining)
                if start:
                    # The first bytes may be in the middle of a UTF-8 line.
                    suffix = piece.partition(b'\n')[2]
                    if suffix:
                        piece = suffix
                pieces.insert(0, piece)
                remaining -= min(size, remaining)
                if remaining <= 0:
                    break
            lines = b''.join(pieces).decode('utf-8', errors='replace').splitlines()
            return '\n'.join(lines[-max(20, min(max_lines, 500)):])
