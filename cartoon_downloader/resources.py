"""Locate installed resources and load migrations in source and compiled builds."""
from __future__ import annotations

import sys
from pathlib import Path


def installation_root() -> Path:
    if '__compiled__' in globals():
        # The standalone backend lives one level below the desktop launcher.
        # Nuitka exposes a python.exe placeholder inside the backend directory.
        # Use only that directory; no separate Python interpreter is shipped.
        return Path(sys.executable).resolve().parent.parent
    return Path(__file__).resolve().parents[1]


def migration_sources(directory: Path) -> list[tuple[str, str]]:
    if '__compiled__' in globals():
        # Generated in the private build workspace, then compiled into the EXE.
        from ._embedded import MIGRATIONS
        return list(MIGRATIONS)
    return [(path.name, path.read_text(encoding='utf-8'))
            for path in sorted(directory.glob('*.sql'))]


def embedded_static(relative: str) -> bytes | None:
    if '__compiled__' in globals():
        from ._embedded import STATIC
        return STATIC.get(relative)
    return None
