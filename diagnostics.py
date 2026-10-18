from contextlib import closing
from pathlib import Path
import json
import platform
import sqlite3
import sys

from cartoon_downloader.local_server import collect_diagnostics
from cartoon_downloader.paths import application_paths
from cartoon_downloader.resources import installation_root
from cartoon_downloader import __version__


def main(root=None, *, data_dir: Path | None = None):
    installation = installation_root()
    paths = application_paths(Path(root) if root is not None else installation, data_dir=data_dir)
    print(f'Cartoon Downloader Desktop v{__version__} diagnostics')
    print('Python:', sys.version.replace('\n', ' '))
    print('Platform:', platform.platform())
    print(json.dumps(collect_diagnostics(paths.resources), ensure_ascii=False, indent=2))
    print('Data folder:', paths.data)
    runtime_info = paths.resources / 'tools/webview2/DEPENDENCY.json'
    if runtime_info.is_file():
        print('Window: native WinForms; bundled WebView2 Fixed Version',
              json.loads(runtime_info.read_text(encoding='utf-8'))['runtime_version'])
    db_path = paths.data / 'data' / 'cartoons.db'
    if not db_path.is_file():
        print('SQLite: database has not been created yet')
        return
    # No migrations, recovery, worker threads or settings writes during diagnosis.
    with closing(sqlite3.connect(db_path.resolve().as_uri() + '?mode=ro', uri=True)) as con:
        con.execute('SELECT 1 FROM schema_migrations LIMIT 1').fetchone()
    print('SQLite: OK', db_path)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Read-only Cartoon Downloader diagnostics')
    parser.add_argument('--data-dir', type=Path)
    main(data_dir=parser.parse_args().data_dir)
