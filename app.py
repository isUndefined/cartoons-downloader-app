from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from cartoon_downloader.local_server import create_server
from cartoon_downloader.paths import application_paths
from cartoon_downloader.resources import installation_root
from cartoon_downloader import __version__


def root_dir():
    return installation_root()


def open_ui(url: str, *, profile_dir: Path | None = None):
    root = root_dir()
    candidates = [root / 'CartoonDownloader.exe',
                  root / 'dist' / f'CartoonDownloader-{__version__}' / 'CartoonDownloader.exe']
    host = next((path for path in candidates if path.is_file()), None)
    if host is None:
        raise RuntimeError('Native window is missing. Run packaging/build_windows.py with the bundled Python first.')
    profile = profile_dir or application_paths(root).data / 'data' / 'webview2'
    return subprocess.Popen([str(host), '--attach-url', url, '--ui-profile', str(profile)])


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--port', type=int, default=0)
    p.add_argument('--no-browser', action='store_true')
    p.add_argument('--desktop-host', action='store_true', help=argparse.SUPPRESS)
    p.add_argument('--data-dir', type=Path, help='Store database, logs and relative downloads in this folder')
    a = p.parse_args()
    try:
        paths = application_paths(root_dir(), data_dir=a.data_dir)
        paths.data.mkdir(parents=True, exist_ok=True)
        os.chdir(paths.data)
        server, application = create_server(paths.data, port=a.port, resource_root=paths.resources)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr, flush=True)
        return 1
    port = server.server_address[1]
    url = f'http://127.0.0.1:{port}'
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        for _ in range(30):
            try:
                with urllib.request.urlopen(url + '/api/health', timeout=.3) as r:
                    if r.status == 200:
                        break
            except OSError:
                time.sleep(.1)
        else:
            raise RuntimeError('Local server did not start')
        print(f'Cartoon Downloader v{__version__} running at {url}', flush=True)
        window = None
        if a.desktop_host:
            print('Desktop host: ' + json.dumps({'url': url, 'profile': str(paths.data / 'data' / 'webview2')}), flush=True)
        elif not a.no_browser:
            application.ui_lifetime.arm()
            window = open_ui(url, profile_dir=paths.data / 'data' / 'webview2')
        last_tick = time.monotonic()
        while True:
            current_tick = time.monotonic()
            if current_tick - last_tick > 30:
                application.ui_lifetime.defer_after_pause(current_tick - last_tick)
            last_tick = current_tick
            if window is not None and window.poll() is not None:
                break
            if application.ui_lifetime.should_stop():
                break
            application.ui_lifetime.exit_requested.wait(.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
        t.join()


if __name__ == '__main__':
    sys.exit(main())
