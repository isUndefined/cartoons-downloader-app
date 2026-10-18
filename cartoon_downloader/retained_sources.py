"""Explicit cleanup of terminal device jobs; accepts job IDs, never paths."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


class RetainedSources:
    def __init__(self, queue):
        self.queue = queue
        self.db = queue.db
        self.temp = (queue.root / 'temp').absolute()

    def _inventory(self, job: dict, references: list[Path]) -> dict | None:
        folder = self.temp / f"job-{job['id']}"
        # Staging is flat. Refuse redirected paths and unexpected subdirectories
        # instead of recursively deleting content whose ownership is unclear.
        if (self.temp.is_symlink() or self.temp.is_junction()
                or folder.is_symlink() or folder.is_junction()
                or not folder.is_dir() or folder.resolve().parent != self.temp.resolve()):
            return None
        resolved = folder.resolve()
        if any(path.is_relative_to(resolved) for path in references):
            return None
        files = []
        for path in sorted(folder.iterdir()):
            if (path.is_symlink() or path.is_junction() or not path.is_file()
                    or path.resolve().parent != resolved):
                return None
            stat = path.stat()
            files.append({'name': path.name, 'size': stat.st_size,
                          'mtime_ns': stat.st_mtime_ns, 'ctime_ns': stat.st_ctime_ns})
        if not any(f"[{job['youtube_id']}]" in item['name']
                   and Path(item['name']).suffix.lower() in {'.mp4', '.mkv', '.webm', '.mov', '.m4v'}
                   for item in files):
            return None
        fingerprint = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
        return {'job_id': job['id'], 'title': job['title'], 'status': job['status'],
                'path': str(folder), 'files': files, 'size': sum(item['size'] for item in files),
                'fingerprint': fingerprint}

    def list(self) -> list[dict]:
        with self.queue.lock:
            with self.db.connect() as con:
                jobs = [dict(row) for row in con.execute(
                    "SELECT j.id,j.status,v.title,v.youtube_id FROM download_jobs j "
                    "JOIN videos v ON v.id=j.video_id WHERE j.target_type='device' "
                    "AND j.status IN ('failed','cancelled') ORDER BY j.id DESC"
                )]
                references = [Path(row[0]).resolve() for row in con.execute(
                    "SELECT file_path FROM videos WHERE file_path IS NOT NULL AND file_path!=''"
                )]
            result = []
            for job in jobs:
                if job['id'] == self.queue.running_job_id or job['id'] in self.queue.processes:
                    continue
                try:
                    item = self._inventory(job, references)
                    if item:
                        result.append(item)
                except OSError:
                    # A locked or disappearing file is not eligible for cleanup.
                    continue
            return result

    def delete(self, selections) -> dict:
        if not isinstance(selections, list) or not 1 <= len(selections) <= 100:
            raise ValueError('Select between 1 and 100 retained sources')
        seen = set()
        for item in selections:
            if (not isinstance(item, dict) or type(item.get('job_id')) is not int
                    or item['job_id'] <= 0 or item['job_id'] in seen
                    or not isinstance(item.get('fingerprint'), str)):
                raise ValueError('Invalid retained source selection')
            seen.add(item['job_id'])
        with self.queue.lock:
            current = {item['job_id']: item for item in self.list()}
            # Validate the whole selection before removing any file. A stale UI
            # must never silently authorize a different set of files.
            for selected in selections:
                item = current.get(selected['job_id'])
                if not item or item['fingerprint'] != selected['fingerprint']:
                    raise ValueError('Selected source changed or is in use. Refresh the list.')
            deleted, errors = [], []
            for selected in selections:
                item = current[selected['job_id']]
                folder = Path(item['path'])
                try:
                    # No recursive deletion: only the inspected files and then
                    # the now-empty, contained job directory are removed.
                    for entry in item['files']:
                        path = folder / entry['name']
                        if path.resolve().parent != self.temp.resolve() / folder.name:
                            raise ValueError('Unsafe retained source path')
                        path.unlink()
                    folder.rmdir()
                    deleted.append(item['job_id'])
                except OSError as exc:
                    errors.append({'job_id': item['job_id'], 'error': str(exc)})
            return {'deleted': deleted, 'errors': errors}
