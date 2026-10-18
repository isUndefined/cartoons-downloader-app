"""Resolve immutable application resources separately from writable user data."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ApplicationPaths:
    resources: Path
    data: Path


def application_paths(installation: Path, *, data_dir: Path | None = None) -> ApplicationPaths:
    """An installer supplies installed.marker beside the launcher; ZIPs stay portable.

    Resolution is read-only, including for diagnostics. Resources inside a frozen
    bundle may differ from the directory containing its executable.
    """
    installation = Path(installation).resolve()
    bundled = getattr(sys, '_MEIPASS', None) if getattr(sys, 'frozen', False) else None
    resources = Path(bundled).resolve() if bundled else installation
    if data_dir is not None:
        data = Path(data_dir).expanduser().resolve()
    elif (installation / 'installed.marker').is_file():
        local = Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local')
        if not local.is_absolute():
            raise RuntimeError('LOCALAPPDATA must be an absolute path')
        data = (local / 'Cartoon Downloader').resolve()
    else:
        data = installation
    return ApplicationPaths(resources, data)
