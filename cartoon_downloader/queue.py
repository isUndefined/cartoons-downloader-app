from __future__ import annotations

import queue as pyqueue
import subprocess
import threading
from pathlib import Path

from .db import Database, now_iso
from .devices import DeviceManager
from .tooling import Tooling
from .processes import terminate_process
from .logs import LogStore
from .retained_sources import RetainedSources
from .download_runner import DownloadRunner, download_update, error_detail
from .local_files import LocalFiles
from .device_transfer import DeviceTransfer, VerifiedTransfer


class Cancelled(Exception):
    pass


class DownloadQueue:
    """Job transitions: queued -> downloading -> processing -> completed,
    or queued -> transferring -> verifying -> completed when reusing a file.
    Downloads for a device download and, when needed, merge before transferring.
    Every active state may become cancelled or failed. Normal processing leaves
    terminal states alone; startup recovery may complete an interrupted
    finalization only with a receipt belonging to that exact job.
    Videos stay downloaded while an existing file is sent to a device; otherwise
    they go pending -> queued -> downloading -> downloaded/device_only, and
    return to pending on failure/cancellation. Completion and cancellation share
    ``lock`` so exactly one can commit the final result.
    """
    ACTIVE = {'queued', 'downloading', 'processing', 'transferring', 'verifying'}

    def __init__(self, db: Database, devices: DeviceManager, root: Path, logs: LogStore | None = None,
                 *, resource_root: Path | None = None):
        self.db, self.devices, self.root = db, devices, Path(root)
        self.work_q: pyqueue.Queue[int | None] = pyqueue.Queue()
        self.cancel_events: dict[int, threading.Event] = {}
        self.processes: dict[int, subprocess.Popen] = {}
        self.runtime: dict[int, dict] = {}
        self.lock = threading.RLock()
        self.stopping = threading.Event()
        self.running_job_id = None
        self.preserved_staging: set[int] = set()
        self.tooling = Tooling(resource_root if resource_root is not None else self.root)
        self.downloader = DownloadRunner()
        self.files = LocalFiles(self.root)
        self.device_transfer = DeviceTransfer(self.devices)
        self.job_log_dir = self.root / 'logs' / 'jobs'
        self.job_log_dir.mkdir(parents=True, exist_ok=True)
        self.logs = logs or LogStore(self.root, self.db)
        self.retained_sources = RetainedSources(self)
        self._reconcile_existing_local_downloads()
        self._restore_queued_jobs()
        self.worker = threading.Thread(target=self._worker, daemon=True, name='download-queue')
        self.worker.start()

    def close(self):
        self.stopping.set()
        with self.lock:
            job_id = self.running_job_id
        if job_id is not None:
            self.cancel(job_id)
        self.work_q.put(None)
        if self.worker.is_alive():
            self.worker.join()

    def _reconcile_existing_local_downloads(self):
        """Recover only our interrupted finalization, never infer success by name.

        A previous download of the same video says nothing about a later job.
        The receipt is written after promotion and before the completion commit.
        Old builds without receipts retain their failed state for an explicit retry.
        """
        with self.db.connect() as con:
            jobs = [dict(row) for row in con.execute(
                "SELECT * FROM download_jobs WHERE target_type='local' "
                "AND status='failed' AND phase='interrupted'"
            )]
        for job in jobs:
            try:
                receipt = self.files.finalized_receipt(job['id'])
                if receipt is None:
                    continue
                target = Path(receipt['path'])
                stat = target.stat()
                stamp = now_iso()
                with self.db.tx() as con:
                    # A newer attempt, including a device transfer, owns its state.
                    if con.execute(
                        'SELECT 1 FROM download_jobs WHERE video_id=? AND id>?',
                        (job['video_id'], job['id']),
                    ).fetchone():
                        continue
                    con.execute(
                        "UPDATE download_jobs SET status='completed',phase='completed',progress=100,"
                        "error=NULL,last_message='Recovered finalized file',actual_quality=?,finished_at=? "
                        "WHERE id=? AND status='failed' AND phase='interrupted'",
                        (receipt.get('actual_quality'), stamp, job['id']),
                    )
                    con.execute(
                        "UPDATE videos SET status='downloaded',downloaded_at=?,file_path=?,"
                        "file_size=?,updated_at=? WHERE id=?",
                        (stamp, str(target), stat.st_size, stamp, job['video_id']),
                    )
                self.files.receipt_path(job['id']).unlink(missing_ok=True)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                self._log(job['id'], f'Finalization recovery skipped: {exc}')

    def _restore_queued_jobs(self):
        with self.db.connect() as con:
            ids = [r[0] for r in con.execute("SELECT id FROM download_jobs WHERE status='queued' ORDER BY position,id")]
        for job_id in ids:
            self.work_q.put(job_id)

    def snapshot(self):
        jobs = self.db.list_jobs()
        with self.lock:
            runtime = {k: v.copy() for k, v in self.runtime.items()}
        for job in jobs:
            job.update(runtime.get(job['id'], {}))
        return jobs

    def enqueue(self, video_ids, target_type, device_serial=None):
        if self.stopping.is_set():
            raise ValueError('Application is shutting down')
        if target_type not in {'local', 'device'}:
            raise ValueError('target_type must be local or device')
        if target_type == 'device' and not device_serial:
            raise ValueError('device_serial is required for device downloads')
        existing = set()
        if target_type == 'device':
            existing = set(self.devices.scan_folder(device_serial).get('youtube_ids') or [])
        settings = self.db.settings()
        default_quality = int(settings.get('default_download_quality') or 720)
        if default_quality not in {360, 480, 720, 1080}:
            default_quality = 720
        now, job_ids, skipped = now_iso(), [], []
        with self.db.tx() as con:
            max_pos = con.execute('SELECT COALESCE(MAX(position),0) FROM download_jobs').fetchone()[0]
            for offset, video_id in enumerate(video_ids, 1):
                video = con.execute('SELECT id,status,youtube_id,file_path FROM videos WHERE id=?', (video_id,)).fetchone()
                allowed = {'pending'} if target_type == 'local' else {'pending', 'downloaded'}
                if not video or video['status'] not in allowed:
                    continue
                reuse_local = target_type == 'device' and video['status'] == 'downloaded'
                if reuse_local and (not video['file_path'] or not Path(video['file_path']).is_file()):
                    raise ValueError('The downloaded local file no longer exists. Download the video again before sending it to a device.')
                if video['youtube_id'] in existing:
                    skipped.append(video_id)
                    continue
                if con.execute(
                    "SELECT 1 FROM download_jobs WHERE video_id=? AND status IN ('queued','downloading','processing','transferring','verifying')",
                    (video_id,),
                ).fetchone():
                    continue
                cur = con.execute(
                    "INSERT INTO download_jobs(video_id,target_type,target_device_serial,status,phase,position,created_at,last_message,requested_quality) VALUES(?,?,?,'queued','queued',?,?,?,?)",
                    (video_id, target_type, device_serial, max_pos + offset, now, 'Waiting to send local file' if reuse_local else 'Waiting in queue', default_quality),
                )
                job_ids.append(cur.lastrowid)
                if not reuse_local:
                    con.execute("UPDATE videos SET status='queued',updated_at=? WHERE id=?", (now, video_id))
        for job_id in job_ids:
            self.cancel_events.setdefault(job_id, threading.Event())
            self.work_q.put(job_id)
        return job_ids, skipped

    def cancel(self, job_id):
        # Serialize cancellation with the final rename and completion commit.
        with self.lock:
            with self.db.tx() as con:
                row = con.execute('SELECT status,video_id FROM download_jobs WHERE id=?', (job_id,)).fetchone()
                if not row or row['status'] not in self.ACTIVE:
                    return
                self.cancel_events.setdefault(job_id, threading.Event()).set()
                stamp = now_iso()
                con.execute(
                    "UPDATE download_jobs SET status='cancelled',phase='cancelled',last_message='Cancelled',finished_at=? WHERE id=?",
                    (stamp, job_id),
                )
                con.execute(
                    "UPDATE videos SET status='pending',updated_at=? WHERE id=? AND status IN ('queued','downloading')",
                    (stamp, row['video_id']),
                )
            self.runtime.pop(job_id, None)
            proc = self.processes.get(job_id)
        if proc and proc.poll() is None:
            terminate_process(proc)

    def log_tail(self, job_id: int, max_lines: int = 160) -> str:
        path = self.job_log_dir / f'job-{job_id}.log'
        if not path.exists():
            return 'No log has been written for this job yet.'
        try:
            return self.logs.tail(path, max_lines)
        except Exception as exc:
            return f'Could not read job log: {exc}'

    def _log_path(self, job_id: int) -> Path:
        return self.job_log_dir / f'job-{job_id}.log'

    def _log(self, job_id: int, text: str):
        self.logs.append(self._log_path(job_id), text)

    def _set_runtime(self, job_id, persist=True, **values):
        with self.lock:
            self._check_cancel(job_id)
            if persist:
                allowed = {'status','phase','progress','downloaded_bytes','total_bytes','speed','eta','last_message','error','actual_quality'}
                updates = {k: v for k, v in values.items() if k in allowed}
                if updates:
                    parts = ','.join(f'{k}=?' for k in updates)
                    with self.db.tx() as con:
                        changed = con.execute(
                            f"UPDATE download_jobs SET {parts} WHERE id=? AND status IN ('queued','downloading','processing','transferring','verifying')",
                            (*updates.values(), job_id),
                        ).rowcount
                        if not changed:
                            raise Cancelled()
            self.runtime.setdefault(job_id, {}).update(values)

    def _clear_runtime(self, job_id):
        with self.lock:
            self.runtime.pop(job_id, None)

    def _check_cancel(self, job_id):
        if self.stopping.is_set() or self.cancel_events.setdefault(job_id, threading.Event()).is_set():
            raise Cancelled()

    def _phase(self, job_id, status, phase, message=None, progress=None):
        values = {'status': status, 'phase': phase}
        if message is not None:
            values['last_message'] = message
        if progress is not None:
            values['progress'] = progress
        self._set_runtime(job_id, **values)

    def _worker(self):
        while True:
            job_id = self.work_q.get()
            try:
                if job_id is None:
                    return
                with self.lock:
                    if self.stopping.is_set():
                        continue
                    self.running_job_id = job_id
                with self.db.connect() as con:
                    row = con.execute('SELECT status FROM download_jobs WHERE id=?', (job_id,)).fetchone()
                if row and row['status'] == 'queued':
                    self._run_job(job_id)
            except Exception as exc:
                self._fail(job_id, exc)
            finally:
                with self.lock:
                    self.running_job_id = None
                self.work_q.task_done()

    def _job_and_video(self, job_id):
        with self.db.connect() as con:
            row = con.execute(
                '''SELECT j.*,v.youtube_id,v.title,v.source_url,v.file_path,v.status AS video_status FROM download_jobs j JOIN videos v ON v.id=j.video_id WHERE j.id=?''',
                (job_id,),
            ).fetchone()
            if not row:
                return None
            job = dict(row)
            job['source_url'] = f"https://www.youtube.com/watch?v={job['youtube_id']}"
            return job

    def _download_output(self, job_id: int, line: str) -> None:
        self._log(job_id, line)
        with self.lock:
            previous = float(self.runtime.get(job_id, {}).get('progress') or 0)
            update = download_update(line, previous)
            if update:
                self._set_runtime(job_id, **update)

    def _download_process(self, job_id: int, process: subprocess.Popen | None) -> None:
        with self.lock:
            if process is None:
                self.processes.pop(job_id, None)
            else:
                self.processes[job_id] = process
                self._check_cancel(job_id)

    def _finish_local(self, job_id: int, job: dict, source: Path, actual_quality: int | None) -> None:
        self._phase(job_id, 'processing', 'processing', 'Finalizing local file…', progress=99)
        configured = str(self.db.settings().get('download_folder') or 'downloads')
        with self.files.prepare_local(job_id, source, configured, lambda: self._check_cancel(job_id)) as prepared:
            self._log(job_id, f'PROMOTE {source} -> {prepared.destination}')
            last_error = None
            for attempt in range(1, 21):
                try:
                    # The slow copy is outside this lock. Only publication,
                    # its recovery receipt and the DB commit serialize with cancel.
                    with self.lock:
                        self._check_cancel(job_id)
                        final = self.files.promote(prepared)
                        self.files.record_finalized(job_id, final, actual_quality)
                        self._complete_job(job_id, job, actual_quality, 'downloaded', final)
                        return
                except PermissionError as exc:
                    last_error = exc
                    self.cancel_events[job_id].wait(min(attempt, 5))
            raise RuntimeError(f'Could not finalize downloaded file after 20 retries: {last_error}')

    def _copy_to_device(self, job_id: int, job: dict, source: Path) -> VerifiedTransfer:
        return self.device_transfer.copy(
            source, serial=job['target_device_serial'], folder=self.db.settings()['device_folder'],
            title=job['title'], youtube_id=job['youtube_id'],
            check_cancel=lambda: self._check_cancel(job_id),
            on_log=lambda line: self._log(job_id, line),
            on_phase=lambda phase, message, progress: self._phase(job_id, phase, phase, message, progress),
        )

    def _complete_job(self, job_id, job, actual_quality, video_status, local_file=None,
                      transfer: VerifiedTransfer | None = None):
        with self.lock:
            self._check_cancel(job_id)
            finished = now_iso()
            message = 'Sent to device' if job['target_type'] == 'device' else 'Completed'
            if actual_quality:
                message += f' \u00b7 {actual_quality}p'
            with self.db.tx() as con:
                changed = con.execute(
                    "UPDATE download_jobs SET status='completed',phase='completed',progress=100,actual_quality=?,last_message=?,finished_at=? WHERE id=? AND status IN ('downloading','processing','transferring','verifying')",
                    (actual_quality, message, finished, job_id),
                ).rowcount
                if not changed:
                    raise Cancelled()
                if transfer is not None:
                    con.execute(
                        "INSERT INTO device_transfers(video_id,device_serial,remote_path,file_size,transferred_at,verified_at) "
                        "VALUES(?,?,?,?,?,?) ON CONFLICT(video_id,device_serial) DO UPDATE SET "
                        "remote_path=excluded.remote_path,file_size=excluded.file_size,"
                        "transferred_at=excluded.transferred_at,verified_at=excluded.verified_at",
                        (job['video_id'], transfer.serial, transfer.remote_path, transfer.file_size, finished, finished),
                    )
                    con.execute('UPDATE download_jobs SET target_path=? WHERE id=?', (transfer.remote_path, job_id))
                if local_file is not None:
                    con.execute(
                        "UPDATE videos SET status='downloaded',downloaded_at=?,file_path=?,file_size=?,updated_at=? WHERE id=?",
                        (finished, str(local_file), local_file.stat().st_size, finished, job['video_id']),
                    )
                else:
                    con.execute('UPDATE videos SET status=?,updated_at=? WHERE id=?', (video_status, finished, job['video_id']))
            self.runtime.pop(job_id, None)
            self._log(job_id, 'COMPLETED')

    def _run_job(self, job_id):
        with self.lock:
            self._check_cancel(job_id)
            job = self._job_and_video(job_id)
            if not job or job['status'] != 'queued':
                return
            log_path = str(self._log_path(job_id))
            started = now_iso()
            requested_quality = int(job.get('requested_quality') or self.db.settings().get('default_download_quality') or 720)
            if requested_quality not in {360, 480, 720, 1080}:
                requested_quality = 720
            reuse_local = (
                job['target_type'] == 'device'
                and job.get('video_status') == 'downloaded'
                and job.get('file_path')
                and Path(job['file_path']).is_file()
            )
            status = 'transferring' if reuse_local else 'downloading'
            message = 'Sending downloaded file to device\u2026' if reuse_local else 'Starting yt-dlp\u2026'
            with self.db.tx() as con:
                changed = con.execute(
                    "UPDATE download_jobs SET status=?,phase=?,started_at=?,error=NULL,progress=0,downloaded_bytes=0,total_bytes=0,speed=NULL,eta=NULL,last_message=?,log_path=?,actual_quality=NULL WHERE id=? AND status='queued'",
                    (status, status, started, message, log_path, job_id),
                ).rowcount
                if not changed:
                    raise Cancelled()
                if not reuse_local:
                    con.execute("UPDATE videos SET status='downloading',unavailable_reason=NULL,updated_at=? WHERE id=?", (started, job['video_id']))
            self._set_runtime(job_id, status=status, phase=status, progress=0, last_message=message)
        self._log(job_id, f"JOB {job_id} video={job['youtube_id']} target={job['target_type']} requested={requested_quality}p")

        if reuse_local:
            final_file = Path(job['file_path'])
            actual_quality = self.tooling.ffprobe_height(final_file)
            self._log(job_id, f'REUSING LOCAL FILE {final_file}')
            transfer = self._copy_to_device(job_id, job, final_file)
            self._complete_job(job_id, job, actual_quality, 'downloaded', transfer=transfer)
            return

        target_dir = self.files.prepare_download(job_id)
        self.downloader.download(
            self.tooling, job['source_url'], target_dir, requested_quality,
            check_cancel=lambda: self._check_cancel(job_id),
            on_output=lambda line: self._download_output(job_id, line),
            on_process=lambda process: self._download_process(job_id, process),
        )
        self._check_cancel(job_id)
        final_file = self.files.find_media(target_dir, job['youtube_id'])
        if not final_file or not final_file.is_file():
            raise RuntimeError('yt-dlp completed successfully but the final media file was not found')
        actual_quality = self.tooling.ffprobe_height(final_file)
        self._log(job_id, f'FINAL FILE {final_file}')
        self._log(job_id, f'QUALITY requested={requested_quality}p actual={actual_quality or "unknown"}p')

        if job['target_type'] == 'device':
            # Keep the source if the device disconnects, verification fails or
            # a transfer is cancelled: Windows may still hold a source stream.
            self.preserved_staging.add(job_id)
            transfer = self._copy_to_device(job_id, job, final_file)
            self._complete_job(job_id, job, actual_quality, 'device_only', transfer=transfer)
            self.preserved_staging.discard(job_id)
        else:
            self._finish_local(job_id, job, final_file, actual_quality)
        self.files.cleanup(job_id)

    def _fail(self, job_id, exc):
        with self.lock:
            job = self._job_and_video(job_id)
            if not job or job['status'] == 'completed':
                return
            cancelled = isinstance(exc, Cancelled) or self.cancel_events.setdefault(job_id, threading.Event()).is_set()
            status = 'cancelled' if cancelled else 'failed'
            error = None if cancelled else error_detail(str(exc), lines=20, limit=3500)
            message = 'Cancelled' if cancelled else 'Download failed'
            if not cancelled:
                self._log(job_id, 'FAILED ' + (error or message))
            with self.db.tx() as con:
                con.execute(
                    'UPDATE download_jobs SET status=?,phase=?,error=?,last_message=?,finished_at=? WHERE id=?',
                    (status, status, error, message, now_iso(), job_id),
                )
                con.execute(
                    "UPDATE videos SET status='pending',updated_at=? WHERE id=? AND status!='downloaded' "
                    "AND NOT EXISTS (SELECT 1 FROM download_jobs WHERE video_id=? AND id!=? "
                    "AND status IN ('queued','downloading','processing','transferring','verifying'))",
                    (now_iso(), job['video_id'], job['video_id'], job_id),
                )
            self.runtime.pop(job_id, None)
        if job_id in self.preserved_staging:
            self._log(job_id, f'SOURCE RETAINED {self.root / "temp" / f"job-{job_id}"}')
            self.preserved_staging.discard(job_id)
        else:
            try:
                self.files.cleanup(job_id)
            except (OSError, ValueError) as cleanup_error:
                self._log(job_id, f'Staging cleanup skipped: {cleanup_error}')
        self._clear_runtime(job_id)
