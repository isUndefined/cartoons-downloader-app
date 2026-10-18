from __future__ import annotations
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse
from .db import Database
from .devices import DeviceManager
from .discovery import DiscoveryManager
from .queue import DownloadQueue
from .instance import InstanceLock
from .ui_lifetime import UiLifetime
from .media import byte_range
from .runtime import RuntimeSnapshots
from .logs import LogStore

def collect_diagnostics(root: Path):
    import sys
    from .tooling import Tooling
    tooling = Tooling(root)

    def item(path):
        ok = path.is_file()
        return {'ok': ok, 'path': str(path), 'error': None if ok else 'Bundled file missing'}
    return {
        'engine': {
            'ok': all(path.is_file() for path in tooling.required_files().values()),
            'path': 'bundled yt-dlp + Deno + FFmpeg', 'error': None,
        },
        'yt-dlp': item(tooling.ytdlp), 'deno': item(tooling.deno),
        'ffmpeg': item(tooling.ffmpeg), 'ffprobe': item(tooling.ffprobe),
        'python': {'ok': True, 'path': sys.executable, 'error': None},
        'device_transport': {
            'ok': os.name == 'nt', 'path': 'Windows MTP' if os.name == 'nt' else '',
            'error': None if os.name == 'nt' else 'Windows only',
        },
    }

class LocalApplication:

    def __init__(self, root: Path, *, resource_root: Path | None = None):
        self.root = Path(root).resolve()
        self.resource_root = Path(resource_root).resolve() if resource_root is not None else self.root
        self.instance_lock = InstanceLock(self.root)
        self.csrf_token = secrets.token_urlsafe(32)
        self.ui_lifetime = UiLifetime()
        try:
            self.db = Database(self.root / 'data' / 'cartoons.db', self.resource_root / 'migrations')
            self.db.recover_interrupted_jobs()
            self.logs = LogStore(self.root, self.db)
            self.logs.prune()
            self.devices = DeviceManager(self.db, self.root)
            self.discovery = DiscoveryManager(self.db, self.root, self.logs, resource_root=self.resource_root)
            self.downloads = DownloadQueue(self.db, self.devices, self.root, self.logs, resource_root=self.resource_root)
            self.runtime = RuntimeSnapshots(self.db, self.discovery)
        except Exception:
            self.instance_lock.close()
            raise

    def close(self):
        self.discovery.stopping.set()
        self.downloads.close()
        self.discovery.close()
        self.instance_lock.close()

    def diagnostics(self):
        return collect_diagnostics(self.resource_root)

    def choose_download_folder(self, initial: str='') -> dict:
        if os.name != 'nt':
            raise RuntimeError('Folder picker is available on Windows only')
        env = os.environ.copy()
        initial_path = str(initial or '').strip()
        if initial_path:
            candidate = Path(initial_path).expanduser()
            if not candidate.is_absolute():
                candidate = (self.root / candidate).resolve()
            env['CD_INITIAL_FOLDER'] = str(candidate)
        else:
            env['CD_INITIAL_FOLDER'] = str((self.root / 'downloads').resolve())
        script = r'''
Add-Type -AssemblyName System.Windows.Forms
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = 'Select local downloads folder'
$dialog.ShowNewFolderButton = $true
$initial = $env:CD_INITIAL_FOLDER
if ($initial -and (Test-Path -LiteralPath $initial)) { $dialog.SelectedPath = $initial }
$owner = New-Object System.Windows.Forms.Form
$owner.ShowInTaskbar = $false
$owner.TopMost = $true
$owner.StartPosition = 'CenterScreen'
$owner.Opacity = 0
$owner.Show()
try { $result = $dialog.ShowDialog($owner) } finally { $owner.Close(); $owner.Dispose() }
if ($result -eq [System.Windows.Forms.DialogResult]::OK) { Write-Output $dialog.SelectedPath }
'''
        flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
        proc = subprocess.run(
            ['powershell.exe', '-NoProfile', '-STA', '-Command', script],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding='utf-8', errors='replace', env=env, timeout=300,
            creationflags=flags,
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or 'Windows folder picker failed').strip()
            raise RuntimeError(detail[-1600:])
        selected = (proc.stdout or '').strip().splitlines()
        path = selected[-1].strip() if selected else ''
        return {'ok': True, 'selected': bool(path), 'path': path}

    def route(self, method, path, query, payload):
        if path == '/api/ui/session' and method == 'POST':
            self.ui_lifetime.update(payload.get('session_id'), payload.get('action'))
            return (200, {'ok': True})
        if path == '/api/shutdown' and method == 'POST':
            self.ui_lifetime.exit_requested.set()
            return (202, {'ok': True})
        if path == '/api/health':
            return (200, {'ok': True, 'runtime': 'stdlib'})
        if path == '/api/diagnostics':
            return (200, self.diagnostics())
        if path == '/api/bootstrap':
            response = {
                'csrf_token': self.csrf_token, 'settings': self.db.settings(),
                'devices': self.db.list_devices(),
                'diagnostics': self.diagnostics(),
            }
            if (query.get('compact') or ['0'])[0] == '1':
                # Bootstrap is always a full snapshot even if stale versions were supplied.
                response.update(self.runtime.snapshot({}))
            else:
                response.update(videos=self.db.list_videos(), jobs=self.downloads.snapshot(),
                                discovery=self.discovery.snapshot())
            return 200, response
        if path == '/api/videos' and method == 'GET':
            return (200, self.db.list_videos((query.get('status') or [None])[0]))
        m = re.fullmatch('/api/videos/(\\d+)/(reject|restore)', path)
        if m and method == 'POST':
            self.db.set_video_status(int(m.group(1)), 'rejected' if m.group(2) == 'reject' else 'pending')
            return (200, {'ok': True})
        if path == '/api/discovery/run' and method == 'POST':
            started = self.discovery.start('fill')
            return (202 if started else 409, {'ok': started, 'state': self.discovery.snapshot()})
        if path == '/api/discovery/refresh' and method == 'POST':
            started = self.discovery.start('refresh')
            return (202 if started else 409, {'ok': started, 'state': self.discovery.snapshot()})
        if path == '/api/discovery/status':
            return (200, self.discovery.snapshot())
        if path == '/api/jobs' and method == 'GET':
            return (200, self.downloads.snapshot())
        if path == '/api/runtime' and method == 'GET':
            if (query.get('compact') or ['0'])[0] == '1':
                return 200, self.runtime.snapshot(query)
            return 200, {
                'jobs': self.downloads.snapshot(), 'videos': self.db.list_videos(),
                'discovery': self.discovery.snapshot(),
            }
        if path == '/api/jobs' and method == 'POST':
            return self.enqueue_request(payload)
        m = re.fullmatch('/api/jobs/(\\d+)/cancel', path)
        if m and method == 'POST':
            self.downloads.cancel(int(m.group(1)))
            return (200, {'ok': True})
        m = re.fullmatch('/api/jobs/(\\d+)/log', path)
        if m and method == 'GET':
            return (200, {'job_id': int(m.group(1)), 'log': self.downloads.log_tail(int(m.group(1)))})
        if path == '/api/devices' and method == 'GET':
            if (query.get('refresh') or ['0'])[0] == '1':
                try:
                    return (200, {'devices': self.devices.refresh(), 'error': None})
                except Exception as exc:
                    return (200, {'devices': self.db.list_devices(), 'error': str(exc)})
            return (200, {'devices': self.db.list_devices(), 'error': None})
        m = re.fullmatch('/api/devices/(.+)/files', path)
        if m and method == 'GET':
            try:
                return (200, {'ok': True, **self.devices.scan_folder(unquote(m.group(1)))})
            except Exception as exc:
                return (400, {'ok': False, 'error': str(exc)})
        if path == '/api/dialog/folder' and method == 'POST':
            return (200, self.choose_download_folder((payload or {}).get('initial', '')))
        if path == '/api/settings' and method == 'GET':
            return (200, self.db.settings())
        if path == '/api/settings' and method == 'PUT':
            self.db.update_settings(payload or {})
            return (200, {'ok': True, 'settings': self.db.settings()})
        if path == '/api/maintenance/sources' and method == 'GET':
            return 200, {'sources': self.downloads.retained_sources.list(), 'logs': {
                'max_bytes': self.logs.MAX_BYTES, 'backups': self.logs.BACKUPS,
                'retention_days': self.logs.RETENTION_DAYS,
            }}
        if path == '/api/maintenance/sources/delete' and method == 'POST':
            result = self.downloads.retained_sources.delete(payload.get('sources'))
            return 200, result
        return (404, {'ok': False, 'error': 'Not found'})

    def enqueue_request(self, payload):
        ids = payload.get('video_ids', [])
        if not isinstance(ids, list) or len(ids) > 1000:
            raise ValueError('video_ids must be a list of at most 1000 IDs')
        if any((isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in ids)):
            raise ValueError('Video IDs must be positive integers')
        target_type = payload.get('target_type', 'local')
        if not isinstance(target_type, str):
            raise ValueError('target_type must be local or device')
        serial = payload.get('device_serial')
        if serial is not None and (not isinstance(serial, str)):
            raise ValueError('device_serial must be a string')
        jobs, skipped = self.downloads.enqueue(ids, target_type, serial)
        return (201, {'ok': True, 'job_ids': jobs, 'skipped_video_ids': skipped})

def make_handler(app: LocalApplication):

    class Handler(BaseHTTPRequestHandler):
        server_version = 'CartoonDownloader/0.28'

        def log_message(self, fmt, *args):
            pass

        def _send_json(self, status, obj):
            data = json.dumps(obj, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(data)

        def _payload(self):
            try:
                n = int(self.headers.get('Content-Length', '0'))
            except ValueError:
                raise ValueError('Invalid Content-Length') from None
            if n < 0 or n > 1024 * 1024:
                raise ValueError('Request body must be at most 1 MB')
            try:
                payload = json.loads(self.rfile.read(n).decode('utf-8')) if n else {}
            except (ValueError, UnicodeError):
                raise ValueError('Invalid JSON request body') from None
            if not isinstance(payload, dict):
                raise ValueError('Request body must be a JSON object')
            return payload

        def _request_allowed(self):
            port = self.server.server_address[1]
            allowed_hosts = {f'127.0.0.1:{port}', f'localhost:{port}'}
            host = self.headers.get('Host', '').lower()
            parsed = urlparse(self.path)
            if host not in allowed_hosts or (parsed.netloc and parsed.netloc.lower() != host):
                self._send_json(403, {'ok': False, 'error': 'Invalid local host'})
                return False
            origin = self.headers.get('Origin')
            if origin is not None and origin != f'http://{host}' or self.headers.get('Sec-Fetch-Site') == 'cross-site':
                self._send_json(403, {'ok': False, 'error': 'Cross-origin requests are not allowed'})
                return False
            if self.command != 'GET':
                if not secrets.compare_digest(self.headers.get('X-CSRF-Token', '').encode('utf-8'), app.csrf_token.encode('utf-8')):
                    self._send_json(403, {'ok': False, 'error': 'Missing or invalid request token'})
                    return False
                if self.headers.get_content_type() != 'application/json':
                    self._send_json(415, {'ok': False, 'error': 'Content-Type must be application/json'})
                    return False
            return True

        def _api(self):
            if not self._request_allowed():
                return
            u = urlparse(self.path)
            try:
                payload = self._payload() if self.command in {'POST', 'PUT', 'PATCH'} else None
                status, obj = app.route(self.command, u.path, parse_qs(u.query), payload)
            except (ValueError, TypeError, sqlite3.IntegrityError) as exc:
                status, obj = (400, {'ok': False, 'error': str(exc)})
            except Exception as exc:
                status, obj = (500, {'ok': False, 'error': str(exc)})
            self._send_json(status, obj)

        def _static(self):
            u = urlparse(self.path)
            if u.path == '/':
                rel = 'index.html'
            elif u.path.startswith('/static/'):
                rel = u.path[len('/static/'):]
            else:
                rel = u.path.lstrip('/')
            base = (app.resource_root / 'static').resolve()
            target = (base / rel).resolve()
            if base not in target.parents and target != base:
                return self.send_error(403)
            if not target.is_file():
                return self.send_error(404)
            data = target.read_bytes()
            ctype = mimetypes.guess_type(str(target))[0] or 'application/octet-stream'
            self.send_response(200)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            self.wfile.write(data)

        def _media_video(self, video_id: int):
            video = app.db.get_video(video_id)
            if not video or not video.get('file_path'):
                return self.send_error(404, 'Downloaded local file was not found')
            target = Path(video['file_path'])
            if not target.is_file():
                return self.send_error(404, 'Downloaded local file no longer exists')
            try:
                media = target.open('rb')
            except FileNotFoundError:
                return self.send_error(404, 'Downloaded local file no longer exists')
            with media:
                return self._stream_media(media, target)

        def _stream_media(self, media, target):
            size = os.fstat(media.fileno()).st_size
            ctype = mimetypes.guess_type(str(target))[0] or 'video/mp4'
            start, end = (0, size - 1)
            range_header = self.headers.get('Range', '')
            partial = False
            if range_header:
                try:
                    start, end = byte_range(range_header, size)
                except ValueError:
                    self.send_response(416)
                    self.send_header('Content-Range', f'bytes */{size}')
                    self.end_headers()
                    return
                partial = True
            length = max(0, end - start + 1)
            self.send_response(206 if partial else 200)
            self.send_header('Content-Type', ctype)
            self.send_header('Accept-Ranges', 'bytes')
            self.send_header('Content-Length', str(length))
            if partial:
                self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
            self.send_header('Cache-Control', 'private, no-store')
            self.end_headers()
            media.seek(start)
            remaining = length
            while remaining > 0:
                chunk = media.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    break
                remaining -= len(chunk)

        @staticmethod
        def _is_client_disconnect(exc):
            return isinstance(exc, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)) or getattr(exc, 'winerror', None) in {10053, 10054}

        def _guard_client_disconnect(self, callback):
            try:
                return callback()
            except OSError as exc:
                if self._is_client_disconnect(exc):
                    return None
                raise

        def do_GET(self):

            def handle():
                path = urlparse(self.path).path
                if not path.startswith('/api/') and (not self._request_allowed()):
                    return
                m = re.fullmatch('/media/video/(\\d+)', path)
                if m:
                    return self._media_video(int(m.group(1)))
                return self._api() if path.startswith('/api/') else self._static()
            return self._guard_client_disconnect(handle)

        def do_POST(self):
            return self._guard_client_disconnect(self._api)

        def do_PUT(self):
            return self._guard_client_disconnect(self._api)
    return Handler

def create_server(root: Path, host='127.0.0.1', port=0, *, resource_root: Path | None = None):
    if host not in {'127.0.0.1', 'localhost'}:
        raise ValueError('The desktop server must listen on loopback')
    app = LocalApplication(root, resource_root=resource_root)

    class LocalServer(ThreadingHTTPServer):
        daemon_threads = False

        def server_close(self):
            try:
                super().server_close()
            finally:
                app.close()
    try:
        server = LocalServer((host, port), make_handler(app))
    except Exception:
        app.close()
        raise
    return (server, app)
