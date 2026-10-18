from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from urllib.parse import quote_plus
from .processes import run_cancellable


class ToolingError(RuntimeError):
    pass


def _creationflags() -> int:
    return subprocess.CREATE_NO_WINDOW if os.name == 'nt' and hasattr(subprocess, 'CREATE_NO_WINDOW') else 0


class Tooling:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.ytdlp = self.root / 'tools' / 'yt-dlp' / 'yt-dlp.exe'
        self.deno = self.root / 'tools' / 'deno' / 'deno.exe'
        self.ffmpeg = self.root / 'tools' / 'ffmpeg' / 'ffmpeg.exe'
        self.ffprobe = self.root / 'tools' / 'ffmpeg' / 'ffprobe.exe'

    def required_files(self) -> dict[str, Path]:
        return {
            'yt-dlp': self.ytdlp,
            'deno': self.deno,
            'ffmpeg': self.ffmpeg,
            'ffprobe': self.ffprobe,
        }

    def assert_ready(self):
        missing = [f'{name}: {path}' for name, path in self.required_files().items() if not path.is_file()]
        if missing:
            raise ToolingError('Bundled toolchain is incomplete:\n' + '\n'.join(missing))

    def base_ytdlp_args(self) -> list[str]:
        self.assert_ready()
        return [
            str(self.ytdlp),
            '--ignore-config',
            '--js-runtimes', f'deno:{self.deno}',
            '--ffmpeg-location', str(self.ffmpeg.parent),
        ]

    def search(self, query: str, limit: int, fresh: bool = False, timeout: int = 75, cancel_check=None) -> list[dict]:
        limit = max(1, min(int(limit), 30))
        query = str(query or '').strip()
        if not query:
            return []

        # ytsearchdate was removed upstream. For the optional fresh pool use
        # YouTube's search URL with the upload-date sort filter. If YouTube
        # changes that filter, Discovery catches this source failure and keeps
        # the relevance pool instead of failing the whole run.
        if fresh:
            source = f'https://www.youtube.com/results?search_query={quote_plus(query)}&sp=CAI%253D'
        else:
            source = f'ytsearch{limit}:{query}'

        cmd = self.base_ytdlp_args() + [
            '--flat-playlist',
            '--dump-single-json',
            '--skip-download',
            '--ignore-errors',
            '--playlist-end', str(limit),
            source,
        ]
        proc = run_cancellable(
            cmd,
            cancel_check=cancel_check,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=timeout,
            creationflags=_creationflags(),
        )
        stdout = (proc.stdout or '').strip()
        stderr = (proc.stderr or '').strip()
        if proc.returncode != 0 and not stdout:
            detail = stderr or f'yt-dlp search failed with exit code {proc.returncode}'
            raise ToolingError(detail[-3500:])
        if not stdout:
            return []
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError as exc:
            # dump-single-json should keep stdout JSON-only. Surface enough
            # context to make failures actionable in discovery.log.
            raise ToolingError(f'yt-dlp returned invalid search JSON: {exc}: {stdout[-1200:]}') from exc

        entries = data.get('entries') if isinstance(data, dict) else None
        if not isinstance(entries, list):
            return []
        result = []
        for entry in entries[:limit]:
            if not isinstance(entry, dict):
                continue
            yid = str(entry.get('id') or '')
            if not yid:
                continue
            thumbs = entry.get('thumbnails') or []
            thumb = entry.get('thumbnail')
            if not thumb and thumbs and isinstance(thumbs, list):
                for item in reversed(thumbs):
                    if isinstance(item, dict) and item.get('url'):
                        thumb = item['url']
                        break
            result.append({
                'id': yid,
                'title': entry.get('title') or yid,
                'channel_id': entry.get('channel_id') or entry.get('uploader_id') or '',
                'uploader_id': entry.get('uploader_id') or '',
                'channel': entry.get('channel') or entry.get('uploader') or '',
                'uploader': entry.get('uploader') or entry.get('channel') or '',
                'duration': entry.get('duration'),
                'view_count': entry.get('view_count'),
                'thumbnail': thumb,
                'thumbnails': thumbs,
                'timestamp': entry.get('timestamp'),
                'upload_date': entry.get('upload_date'),
            })
        return result

    def ffprobe_height(self, media_path: Path, timeout: int = 20) -> int | None:
        if not self.ffprobe.is_file():
            return None
        cmd = [
            str(self.ffprobe), '-v', 'error', '-select_streams', 'v:0',
            '-show_entries', 'stream=height', '-of', 'default=noprint_wrappers=1:nokey=1',
            str(media_path),
        ]
        try:
            proc = subprocess.run(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                encoding='utf-8', errors='replace', timeout=timeout,
                creationflags=_creationflags(),
            )
            if proc.returncode == 0:
                value = (proc.stdout or '').strip().splitlines()
                if value:
                    height = int(value[0].strip())
                    return height if height > 0 else None
        except Exception:
            pass
        return None


def ytdlp_download_command(tooling: Tooling, url: str, output_dir: Path, quality: int) -> list[str]:
    quality = int(quality)
    if quality not in {360, 480, 720, 1080}:
        quality = 720
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Prefer YouTube's separate AVC + AAC tracks at the requested ceiling.
    # This is what enables 720p/1080p even when the best combined format is
    # only 360p. Fall back to other adaptive codecs, then combined video.
    fmt = (
        f"bv[height<={quality}][vcodec~='^avc1']+ba[acodec~='^mp4a']/"
        f'bv[height<={quality}]+ba/'
        f'b[height<={quality}]'
    )
    progress_template = (
        'download:__CD_PROGRESS__|%(progress._percent_str)s|%(progress.downloaded_bytes)s|'
        '%(progress.total_bytes)s|%(progress.total_bytes_estimate)s|%(progress.speed)s|'
        '%(progress.eta)s|%(info.format_id)s|%(info.height)s|%(info.vcodec)s|%(info.acodec)s'
    )
    return tooling.base_ytdlp_args() + [
        '--newline',
        '--progress',
        '--encoding', 'utf-8',
        '--no-playlist',
        '--no-simulate',
        '--socket-timeout', '20',
        '--retries', '5',
        '--fragment-retries', '5',
        '--extractor-retries', '3',
        # Windows can briefly keep a completed media file open (AV/indexer/etc.)
        # exactly when yt-dlp finalizes it. Give file operations a much wider
        # retry window and avoid the HTTP downloader's final .part -> media
        # rename entirely. Downloads happen in an isolated per-job staging dir.
        '--file-access-retries', '20',
        '--retry-sleep', 'file_access:linear=1:5:1',
        '--no-part',
        # Parallel fragment fetching helps DASH/HLS formats. A 10 MB HTTP
        # chunk is intentionally capped at YouTube's documented threshold so
        # chunking can mitigate server-side bandwidth throttling without
        # triggering the >10 MB throttle behavior.
        '--concurrent-fragments', '8',
        '--http-chunk-size', '10M',
        '--progress-delta', '0.5',
        '-f', fmt,
        '--merge-output-format', 'mp4',
        '-o', str(output_dir / '%(title).140B [%(id)s].%(ext)s'),
        '--progress-template', progress_template,
        url,
    ]
