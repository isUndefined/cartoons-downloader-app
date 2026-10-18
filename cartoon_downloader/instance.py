from __future__ import annotations

import os
from pathlib import Path


class InstanceLock:
    """OS-owned lock: a crashed process cannot leave a stale application lock."""

    def __init__(self, root: Path):
        path = Path(root) / 'data' / 'application.lock'
        path.parent.mkdir(parents=True, exist_ok=True)
        self.file = path.open('a+b')
        try:
            if path.stat().st_size == 0:
                self.file.write(b'\0')
                self.file.flush()
            self.file.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.file.close()
            raise RuntimeError('Cartoon Downloader is already running for this folder. Close the existing instance first.') from exc

    def close(self):
        if not self.file.closed:
            # Closing the handle releases the lock without deleting a shared path.
            self.file.close()
