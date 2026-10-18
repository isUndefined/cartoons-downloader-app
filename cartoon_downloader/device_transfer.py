"""Copy and verify an MTP source without committing application state."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .devices import DeviceManager


@dataclass(frozen=True)
class VerifiedTransfer:
    serial: str
    remote_path: str
    file_size: int


class DeviceTransfer:
    def __init__(self, devices: DeviceManager):
        self.devices = devices

    def copy(self, source: Path, *, serial: str, folder: str, title: str, youtube_id: str,
             check_cancel: Callable[[], None], on_log: Callable[[str], None],
             on_phase: Callable[[str, str, int], None]) -> VerifiedTransfer:
        check_cancel()
        self.devices.ensure_online(serial)
        filename = self.devices.safe_remote_filename(title, youtube_id, source.suffix)
        on_phase('transferring', f'Transferring to {serial} via Windows MTP…', 0)
        on_log(f'MTP COPY {source} -> {serial}:{folder}/{filename}')
        receipt = self.devices.copy_file(serial, source, filename, folder, cancel_check=check_cancel)
        check_cancel()
        on_phase('verifying', 'Verifying file on device…', 100)
        expected_size = source.stat().st_size
        if (not isinstance(receipt, dict) or receipt.get('file_size') != expected_size
                or not receipt.get('remote_path')):
            raise RuntimeError('MTP file transfer verification failed')
        return VerifiedTransfer(serial, receipt['remote_path'], expected_size)
