"""Bounded views of the media catalog and failed-job history."""

import math
import sqlite3

PAGE_SIZE = 50
ACTIVE_SQL = "('queued','downloading','processing','transferring','verifying')"
DISCOVERY_SQL = "('pending','failed','unavailable')"
LIBRARY_SQL = "('downloaded','device_only')"

VIDEO_SELECT = '''
    SELECT v.id,v.youtube_id,v.title,v.channel_name,v.duration,v.thumbnail_url,
           v.status,v.file_path,v.updated_at,
           j.id AS job_id,j.status AS job_status,j.requested_quality,j.actual_quality AS job_quality,
           j.target_type,
           (SELECT q.actual_quality FROM download_jobs q
            WHERE q.video_id=v.id AND q.status='completed' AND q.actual_quality IS NOT NULL
            ORDER BY q.id DESC LIMIT 1) AS actual_quality
    FROM videos v
    LEFT JOIN download_jobs j ON j.id=(
        SELECT last.id FROM download_jobs last WHERE last.video_id=v.id ORDER BY last.id DESC LIMIT 1
    )
'''

JOB_SELECT = '''
    SELECT j.*,v.title,v.youtube_id,v.thumbnail_url,v.channel_name
    FROM download_jobs j JOIN videos v ON v.id=j.video_id
'''


def page_number(query: dict, name: str) -> int:
    value = (query.get(name) or ['1'])[0]
    if not isinstance(value, str) or not value.isascii() or not value.isdecimal():
        raise ValueError(f'{name} must be a positive page number')
    number = int(value)
    if not 1 <= number <= 1_000_000:
        raise ValueError(f'{name} must be between 1 and 1000000')
    return number


def pagination(total: int, requested: int) -> dict:
    pages = max(1, math.ceil(total / PAGE_SIZE))
    return {'page': min(requested, pages), 'page_size': PAGE_SIZE, 'total': total, 'pages': pages}


def video_rows(con: sqlite3.Connection, condition: str, parameters=(), *, page=None) -> list[dict]:
    order = ' ORDER BY v.discovered_at DESC,v.score DESC,v.id DESC'
    if page:
        # Limit IDs before looking up per-video job metadata. With an ORDER BY
        # sort SQLite may otherwise evaluate those subqueries for the history.
        ids = [row[0] for row in con.execute(
            'SELECT v.id FROM videos v WHERE ' + condition + order + ' LIMIT ? OFFSET ?',
            (*parameters, PAGE_SIZE, (page['page'] - 1) * PAGE_SIZE),
        )]
        if not ids:
            return []
        condition = 'v.id IN (' + ','.join('?' for _ in ids) + ')'
        parameters = ids
    sql = VIDEO_SELECT + ' WHERE ' + condition + order
    result = []
    for row in con.execute(sql, parameters):
        video = dict(row)
        job_id = video.pop('job_id')
        job_status = video.pop('job_status')
        requested_quality = video.pop('requested_quality')
        actual_quality = video.pop('job_quality')
        target_type = video.pop('target_type')
        video['latest_job'] = None if job_id is None else {
            'id': job_id, 'video_id': video['id'], 'status': job_status,
            'requested_quality': requested_quality, 'actual_quality': actual_quality,
            'target_type': target_type,
        }
        result.append(video)
    return result


def catalog_snapshot(con: sqlite3.Connection, requested: dict) -> dict:
    counts = {row['status']: row['count'] for row in con.execute(
        'SELECT status,COUNT(*) AS count FROM videos GROUP BY status'
    )}
    pending = sum(counts.get(status, 0) for status in ('pending', 'failed', 'unavailable'))
    downloaded = sum(counts.get(status, 0) for status in ('downloaded', 'device_only'))
    failures = con.execute("SELECT COUNT(*) FROM download_jobs WHERE status='failed'").fetchone()[0]
    active = con.execute(f'SELECT COUNT(*) FROM download_jobs WHERE status IN {ACTIVE_SQL}').fetchone()[0]
    pages = {
        'discovery': pagination(pending, requested['discovery']),
        'downloaded': pagination(downloaded, requested['downloaded']),
        'failures': pagination(failures, requested['failures']),
    }
    discovery = video_rows(con, f'v.status IN {DISCOVERY_SQL}', page=pages['discovery'])
    library = video_rows(con, f'v.status IN {LIBRARY_SQL}', page=pages['downloaded'])
    active_videos = video_rows(con, f'v.id IN (SELECT video_id FROM download_jobs WHERE status IN {ACTIVE_SQL})')
    videos = {video['id']: video for video in [*discovery, *library, *active_videos]}
    return {
        'videos': list(videos.values()),
        'discovery_ids': [video['id'] for video in discovery],
        'downloaded_ids': [video['id'] for video in library],
        'counts': {'pending': pending, 'ready': counts.get('pending', 0),
                   'active': active, 'downloaded': downloaded},
        'pages': pages,
    }


def job_snapshot(con: sqlite3.Connection, requested_page: int) -> list[dict]:
    total = con.execute("SELECT COUNT(*) FROM download_jobs WHERE status='failed'").fetchone()[0]
    page = pagination(total, requested_page)
    active = con.execute(JOB_SELECT + f''' WHERE j.status IN {ACTIVE_SQL}
        ORDER BY CASE WHEN j.status='queued' THEN 1 ELSE 0 END,j.position,j.id''')
    failures = con.execute(JOB_SELECT + ''' WHERE j.status='failed' ORDER BY j.id DESC LIMIT ? OFFSET ?''',
                           (PAGE_SIZE, (page['page'] - 1) * PAGE_SIZE))
    return [dict(row) for row in active] + [dict(row) for row in failures]
