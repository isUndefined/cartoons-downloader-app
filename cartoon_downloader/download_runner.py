"""Run yt-dlp and interpret its output without accessing jobs or the database."""
from __future__ import annotations

import os
import queue
import re
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path

from .processes import terminate_process
from .tooling import Tooling, ytdlp_download_command


def error_detail(text: str, lines: int = 16, limit: int = 3500) -> str:
    items = [line.strip() for line in (text or '').splitlines()
             if line.strip() and line.strip().casefold() not in {'null', 'none'}]
    return '\n'.join(items[-lines:])[-limit:]


def _number(value):
    try:
        if value in ('', 'NA', 'None', 'null', None):
            return None
        return float(str(value).strip().replace('%', '').replace('MiB/s', '').replace('KiB/s', ''))
    except (ValueError, TypeError):
        return None


def download_update(line: str, previous_progress: float = 0) -> dict:
    """Map stream-local progress into one monotonic download/merge timeline."""
    if line.startswith('COMMAND '):
        return {}
    if line.startswith('__CD_PROGRESS__|'):
        parts = line.split('|')
        parts += [''] * max(0, 11 - len(parts))
        percent = max(0.0, min(float(_number(parts[1]) or 0), 100.0))
        height = int(_number(parts[8]) or 0) or None
        has_video = parts[9].strip().casefold() not in {'', 'na', 'none', 'null'}
        has_audio = parts[10].strip().casefold() not in {'', 'na', 'none', 'null'}
        if has_video and not has_audio:
            progress = percent * .82
            message = f'Downloading video {height}p' if height else 'Downloading video'
        elif has_audio and not has_video:
            progress = 82 + percent * .13
            message = 'Downloading audio'
        elif has_video and has_audio:
            progress = percent * .95
            message = f'Downloading {height}p video + audio' if height else 'Downloading video + audio'
        else:
            progress = percent * .95
            message = f'Downloading {height}p' if height else 'Downloading media…'
        eta = _number(parts[6])
        return {
            'status': 'downloading', 'phase': 'downloading',
            'progress': max(previous_progress, min(progress, 95)),
            'downloaded_bytes': int(_number(parts[2]) or 0),
            'total_bytes': int(_number(parts[3]) or _number(parts[4]) or 0),
            'speed': _number(parts[5]), 'eta': int(eta) if eta is not None else None,
            'last_message': message,
        }
    lower = line.casefold()
    if line.startswith('[youtube] Extracting URL'):
        return {'last_message': 'Reading YouTube metadata…'}
    if any(text in lower for text in ('downloading webpage', 'downloading player', 'solving', 'challenge')):
        return {'last_message': line}
    if line.startswith('[download] Destination:'):
        return {'status': 'downloading', 'phase': 'downloading', 'last_message': 'Starting media download…'}
    if line.startswith(('[Merger]', '[VideoRemuxer]', '[VideoConvertor]')):
        return {'status': 'processing', 'phase': 'processing', 'progress': 97,
                'last_message': 'Merging video and audio…'}
    return {}


class DownloadRunner:
    def __init__(self, *, idle_timeout: float = 180):
        self.idle_timeout = idle_timeout

    def download(self, tooling: Tooling, url: str, directory: Path, quality: int, *,
                 check_cancel: Callable[[], None], on_output: Callable[[str], None],
                 on_process: Callable[[subprocess.Popen | None], None]) -> None:
        check_cancel()
        command = ytdlp_download_command(tooling, url, directory, quality)
        on_output('COMMAND ' + subprocess.list2cmdline(command))
        check_cancel()
        proc = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding='utf-8', errors='replace', bufsize=1,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0,
        )
        output: queue.Queue[str | Exception | None] = queue.Queue()

        def read_output():
            try:
                for raw in proc.stdout:
                    output.put(raw.rstrip('\r\n'))
            except (OSError, ValueError) as exc:
                output.put(exc)
            finally:
                output.put(None)

        reader = threading.Thread(target=read_output, daemon=True, name='yt-dlp-output')
        reader_started = False
        recent = []
        last_output = time.monotonic()
        try:
            # Registration may discover cancellation which raced with Popen.
            # The finally block still owns and terminates that new process.
            on_process(proc)
            check_cancel()
            reader.start()
            reader_started = True
            while True:
                check_cancel()
                try:
                    line = output.get(timeout=min(.5, self.idle_timeout))
                except queue.Empty:
                    if time.monotonic() - last_output > self.idle_timeout:
                        raise RuntimeError(f'yt-dlp produced no output for {self.idle_timeout:g} seconds. See the job log for details.')
                    continue
                if line is None:
                    break
                if isinstance(line, Exception):
                    raise RuntimeError(f'Could not read yt-dlp output: {line}') from line
                last_output = time.monotonic()
                clean = re.sub(r'\x1b\[[0-9;]*m', '', line).strip()[-600:]
                if clean:
                    recent = (recent + [clean])[-30:]
                    on_output(clean)
            # yt-dlp can close stdout before exiting; keep cancellation and
            # the same idle deadline active until the process actually stops.
            while proc.poll() is None:
                check_cancel()
                if time.monotonic() - last_output > self.idle_timeout:
                    raise RuntimeError('yt-dlp did not exit after closing its output')
                try:
                    proc.wait(timeout=.1)
                except subprocess.TimeoutExpired:
                    continue
            check_cancel()
            if proc.returncode != 0:
                raise RuntimeError(error_detail('\n'.join(recent), lines=20)
                                   or f'yt-dlp failed with exit code {proc.returncode}')
        finally:
            try:
                terminate_process(proc)
                if reader_started:
                    reader.join(timeout=5)
                if reader.is_alive():
                    raise RuntimeError('yt-dlp output reader did not stop')
                proc.stdout.close()
            finally:
                on_process(None)
