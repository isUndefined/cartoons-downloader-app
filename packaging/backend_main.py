"""Compiled backend entry point; the desktop launcher owns its lifetime."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import app
import diagnostics


def main() -> int:
    # The desktop host reads a line-delimited UTF-8 startup handshake.
    sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
    sys.stderr.reconfigure(encoding='utf-8', line_buffering=True)
    if '--diagnostics' in sys.argv[1:]:
        parser = argparse.ArgumentParser(description='Read-only application diagnostics')
        parser.add_argument('--diagnostics', action='store_true')
        parser.add_argument('--data-dir', type=Path)
        arguments = parser.parse_args()
        diagnostics.main(data_dir=arguments.data_dir)
        return 0
    return app.main() or 0


if __name__ == '__main__':
    raise SystemExit(main())
