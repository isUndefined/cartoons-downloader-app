from __future__ import annotations

import json
import math
import re
import threading
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .db import Database, now_iso
from .tooling import Tooling
from .logs import LogStore


@dataclass
class RuntimeState:
    running: bool = False
    message: str = ''
    progress: float = 0.0
    run_id: int | None = None
    error: str | None = None
    mode: str = 'fill'


class DiscoveryManager:
    """Bounded discovery with two explicit product actions.

    ``fill`` keeps the New list at the configured target.  If the target is 10
    and 8 pending recommendations remain, only 2 new rows are added.

    ``refresh`` replaces the pending/New list with a completely new target-sized
    set.  Replaced rows remain in the database with status ``refreshed`` so they
    are remembered and never shown again by a later refresh.
    """

    def __init__(self, db: Database, root, logs: LogStore | None = None,
                 *, resource_root: Path | None = None):
        self.db = db
        self.root = Path(root)
        self.state = RuntimeState()
        self.tooling = Tooling(resource_root if resource_root is not None else self.root)
        self.lock = threading.Lock()
        self.stopping = threading.Event()
        self.worker = None
        (self.root / 'logs').mkdir(parents=True, exist_ok=True)
        self.log_path = self.root / 'logs' / 'discovery.log'
        self.logs = logs or LogStore(self.root, self.db)

    def snapshot(self):
        with self.lock:
            return self.state.__dict__.copy()

    def start(self, mode: str = 'fill') -> bool:
        if mode not in {'fill', 'refresh'}:
            raise ValueError(f'Unknown discovery mode: {mode}')
        with self.lock:
            if self.state.running or self.stopping.is_set():
                return False
            message = 'Refreshing recommendations…' if mode == 'refresh' else 'Checking New list…'
            self.state = RuntimeState(running=True, message=message, mode=mode)
            self.worker = threading.Thread(target=self._run, args=(mode,), daemon=True, name=f'discovery-{mode}')
            self.worker.start()
        return True

    def close(self):
        with self.lock:
            self.stopping.set()
            worker = self.worker
        if worker and worker.is_alive():
            worker.join()

    def _check_stopping(self):
        if self.stopping.is_set():
            raise RuntimeError('Discovery interrupted by application shutdown')

    def _set(self, **kwargs):
        with self.lock:
            for k, v in kwargs.items():
                setattr(self.state, k, v)

    def _log(self, text: str):
        self.logs.append(self.log_path, text)

    @staticmethod
    def _norm(value: str | None) -> str:
        return (value or '').strip().casefold()

    def _search(self, query: str, limit: int, fresh: bool = False) -> dict:
        mode = 'fresh' if fresh else 'relevance'
        self._log(f'SEARCH {mode} query={query!r} limit={limit}')
        entries = self.tooling.search(query, limit=limit, fresh=fresh, cancel_check=self._check_stopping)
        return {'entries': entries}

    @staticmethod
    def _candidate_budget(slots: int) -> int:
        # Small top-ups should stay cheap; a full 10-card refresh normally sees
        # ~24 unique raw candidates and can expand once to a hard cap of 40.
        return max(12, min(30, slots * 2 + 4))

    def _run(self, mode: str):
        run_id = None
        try:
            settings = self.db.settings()
            queries = [x['query'] for x in settings['search_queries'] if x.get('enabled')]
            if not queries:
                raise RuntimeError('No enabled search queries. Open Settings and add at least one query.')

            target = max(1, int(settings['target_pending']))
            with self.db.connect() as con:
                known = {r[0] for r in con.execute('SELECT youtube_id FROM videos')}
                pending_rows = [dict(r) for r in con.execute(
                    "SELECT youtube_id,channel_id,channel_name FROM videos WHERE status='pending'"
                )]

            if mode == 'fill':
                slots = max(0, target - len(pending_rows))
                base_channel_counts: dict[str, int] = defaultdict(int)
                for row in pending_rows:
                    channel = row.get('channel_id') or row.get('channel_name') or row['youtube_id']
                    base_channel_counts[channel] += 1
            else:
                slots = target
                base_channel_counts = defaultdict(int)

            with self.db.tx() as con:
                run_id = con.execute(
                    "INSERT INTO discovery_runs(started_at,status) VALUES(?, 'running')", (now_iso(),)
                ).lastrowid
            self._set(run_id=run_id)
            self._log(
                f'=== discovery run {run_id} mode={mode} target={target} '
                f'pending_before={len(pending_rows)} slots={slots} ==='
            )

            if slots == 0:
                with self.db.tx() as con:
                    con.execute(
                        "UPDATE discovery_runs SET finished_at=?,status='completed',candidates_found=0,candidates_selected=0 WHERE id=?",
                        (now_iso(), run_id),
                    )
                self._set(
                    running=False,
                    progress=1.0,
                    message=f'New list already has {len(pending_rows)}/{target} cartoons',
                    error=None,
                )
                return

            include_recent = bool(settings['discovery_include_recent'])
            modes_per_query = 2 if include_recent else 1
            total_searches = max(1, len(queries) * modes_per_query)
            initial_budget = self._candidate_budget(slots)
            max_unique = max(initial_budget, min(40, slots * 4))
            configured_limit = max(2, min(int(settings.get('search_results_per_query') or 6), 10))
            initial_limit = max(2, min(configured_limit, math.ceil(initial_budget / total_searches)))
            topup_limit = max(initial_limit, min(10, math.ceil(max_unique / total_searches)))

            raw: dict[str, dict[str, Any]] = {}
            warnings: list[str] = []

            def collect(limit: int, progress_start: float, progress_end: float, *, topup: bool = False):
                done = 0
                for query in queries:
                    modes = [('relevance', False)]
                    if include_recent:
                        modes.append(('fresh', True))
                    for source_type, fresh_mode in modes:
                        self._check_stopping()
                        prefix = 'Looking for more' if topup else ('Refreshing' if mode == 'refresh' else 'Searching')
                        self._set(message=f'{prefix}: {query} ({source_type})')
                        try:
                            result = self._search(query, limit, fresh=fresh_mode)
                            self._check_stopping()
                        except RuntimeError as exc:
                            if source_type == 'fresh':
                                warning = f'{query}: recent search unavailable'
                                if warning not in warnings:
                                    warnings.append(warning)
                                self._log(f'WARN recent search failed for {query}: {exc}')
                                done += 1
                                self._set(progress=progress_start + (progress_end-progress_start) * done / total_searches)
                                continue
                            raise

                        for rank, entry in enumerate((result.get('entries') or [])[:limit], start=1):
                            if not entry or not entry.get('id'):
                                continue
                            yid = str(entry['id'])
                            if not re.fullmatch(r'[A-Za-z0-9_-]{11}', yid):
                                continue
                            if yid not in raw and len(raw) >= max_unique:
                                continue
                            item = raw.setdefault(yid, {
                                'youtube_id': yid,
                                'title': entry.get('title') or yid,
                                'channel_id': entry.get('channel_id') or entry.get('uploader_id') or '',
                                'channel_name': entry.get('channel') or entry.get('uploader') or '',
                                'duration': entry.get('duration'),
                                'view_count': entry.get('view_count'),
                                'thumbnail_url': entry.get('thumbnail') or ((entry.get('thumbnails') or [{}])[-1].get('url')),
                                'source_url': f'https://www.youtube.com/watch?v={yid}',
                                'hits': [],
                            })
                            key = (query, source_type)
                            previous = next((h for h in item['hits'] if (h['query'], h['source_type']) == key), None)
                            if previous is None:
                                item['hits'].append({'query': query, 'source_type': source_type, 'rank': rank})
                            elif rank < previous['rank']:
                                previous['rank'] = rank
                            for field in ('duration', 'view_count'):
                                if not item.get(field) and entry.get(field):
                                    item[field] = entry[field]

                        done += 1
                        self._set(progress=progress_start + (progress_end-progress_start) * done / total_searches)

            romanian = [x for x in settings['romanian_hints'] if x.get('enabled')]
            excludes = [x for x in settings['exclude_hints'] if x.get('enabled')]
            trusted = [x for x in settings['channel_rules'] if x['rule'] == 'trusted']
            blocked = [x for x in settings['channel_rules'] if x['rule'] == 'blocked']
            min_duration = int(settings['min_duration_minutes']) * 60
            max_per_channel = max(1, int(settings['max_results_per_channel']))

            def rank_and_select(rank_window: int):
                scored = []
                for item in raw.values():
                    text = self._norm(f"{item['title']} {item['channel_name']}")
                    channel_key = self._norm(f"{item.get('channel_id','')} {item.get('channel_name','')}")
                    reject = 'known' if item['youtube_id'] in known else None
                    details: dict[str, Any] = {}

                    if not reject:
                        for h in excludes:
                            if self._norm(h['value']) in text:
                                reject = f"exclude:{h['value']}"
                                break
                    if not reject:
                        for rule in blocked:
                            if self._norm(rule['channel_key']) in channel_key:
                                reject = f"blocked:{rule['channel_key']}"
                                break
                    duration = int(item.get('duration') or 0)
                    if not reject and duration and duration < min_duration:
                        reject = 'too_short'

                    score = 0.0
                    hint_score = sum(float(h.get('weight') or 0) for h in romanian if self._norm(h['value']) in text)
                    score += hint_score
                    details['romanian'] = hint_score
                    rel = max([0, *[max(0, rank_window + 1 - x['rank']) for x in item['hits'] if x['source_type'] == 'relevance']])
                    fresh = max([0, *[max(0, rank_window + 1 - x['rank']) for x in item['hits'] if x['source_type'] == 'fresh']])
                    score += rel * 1.35 + fresh * 0.7
                    details['relevance'] = round(rel * 1.35, 2)
                    details['fresh'] = round(fresh * 0.7, 2)
                    views = int(item.get('view_count') or 0)
                    popularity = min(18.0, math.log10(max(views, 1)) * 2.5) if views else 0
                    score += popularity
                    details['popularity'] = round(popularity, 2)
                    trusted_score = 0.0
                    for rule in trusted:
                        if self._norm(rule['channel_key']) in channel_key:
                            trusted_score = max(trusted_score, float(rule.get('weight') or 25))
                    score += trusted_score
                    details['trusted'] = trusted_score
                    item['score'] = round(score, 3)
                    item['score_details'] = details
                    item['reject_reason'] = reject
                    if not reject:
                        scored.append(item)

                scored.sort(key=lambda x: (-x['score'], x['youtube_id']))
                per_channel = defaultdict(int, base_channel_counts)
                selected = []
                for item in scored:
                    channel = item.get('channel_id') or item.get('channel_name') or item['youtube_id']
                    if per_channel[channel] >= max_per_channel:
                        item['reject_reason'] = 'channel_limit'
                        continue
                    item['reject_reason'] = None
                    selected.append(item)
                    per_channel[channel] += 1
                    if len(selected) >= slots:
                        break
                return selected

            collect(initial_limit, 0.02, 0.58)
            self._set(message='Ranking candidates…', progress=0.62)
            selected = rank_and_select(initial_limit)

            if len(selected) < slots and topup_limit > initial_limit and len(raw) < max_unique:
                self._log(f'run {run_id}: initial selected={len(selected)}/{slots}; bounded top-up {initial_limit}->{topup_limit}')
                collect(topup_limit, 0.64, 0.84, topup=True)
                self._set(message='Ranking additional candidates…', progress=0.88)
                selected = rank_and_select(topup_limit)

            selected_ids = {x['youtube_id'] for x in selected}
            candidate_rows = []
            for item in raw.values():
                hit = item['hits'][0] if item['hits'] else {}
                candidate_rows.append((
                    run_id, item['youtube_id'], item['title'], item['channel_name'], hit.get('query'), hit.get('source_type'),
                    hit.get('rank'), item.get('score', 0), 1 if item['youtube_id'] in selected_ids else 0,
                    item.get('reject_reason'), json.dumps(item.get('score_details') or {}, ensure_ascii=False),
                ))

            self._check_stopping()
            with self.db.tx() as con:
                con.executemany(
                    '''INSERT OR IGNORE INTO discovery_candidates(run_id,youtube_id,title,channel_name,query,source_type,source_rank,final_score,accepted,reject_reason,score_details) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                    candidate_rows,
                )
                now = now_iso()
                if mode == 'refresh':
                    # Keep historical IDs in videos so subsequent refreshes can
                    # exclude everything that has already been shown, but hide
                    # the replaced cards from all normal UI filters.
                    con.execute(
                        "UPDATE videos SET status='refreshed',updated_at=? WHERE status='pending'",
                        (now,),
                    )

                actually_added = 0
                for item in selected:
                    cur = con.execute(
                        '''INSERT OR IGNORE INTO videos(youtube_id,title,channel_id,channel_name,duration,view_count,thumbnail_url,source_url,status,score,score_details,discovered_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,'pending',?,?,?,?,?)''',
                        (item['youtube_id'], item['title'], item.get('channel_id'), item.get('channel_name'), item.get('duration'),
                         item.get('view_count'), item.get('thumbnail_url'), item.get('source_url'), item['score'],
                         json.dumps(item['score_details'], ensure_ascii=False), now, now, now),
                    )
                    actually_added += max(0, int(cur.rowcount or 0))

                pending_after = con.execute("SELECT COUNT(*) FROM videos WHERE status='pending'").fetchone()[0]
                con.execute(
                    "UPDATE discovery_runs SET finished_at=?,status='completed',candidates_found=?,candidates_selected=? WHERE id=?",
                    (now_iso(), len(raw), actually_added, run_id),
                )

            self._log(
                f'run {run_id}: mode={mode} raw_unique={len(raw)} added={actually_added}/{slots} '
                f'pending_after={pending_after}/{target} initial_limit={initial_limit} '
                f'topup_limit={topup_limit} max_unique={max_unique}'
            )
            if mode == 'refresh':
                if actually_added >= target:
                    message = f'Refreshed: {actually_added} new cartoons'
                else:
                    message = f'Refreshed: {actually_added} of {target} new cartoons · no more eligible results in the bounded search pool'
            else:
                if actually_added:
                    message = f'Added {actually_added} new cartoon{"s" if actually_added != 1 else ""} · New list {pending_after}/{target}'
                else:
                    message = f'New list {pending_after}/{target} · no additional eligible results found'
            if warnings:
                message += ' · recent search fallback used'
            self._set(running=False, progress=1.0, message=message, error=None)
        except Exception as exc:
            self._log(f'ERROR run {run_id}: {exc}')
            if run_id:
                with self.db.tx() as con:
                    con.execute(
                        "UPDATE discovery_runs SET finished_at=?,status='failed',error=? WHERE id=?",
                        (now_iso(), str(exc), run_id),
                    )
            self._set(running=False, error=str(exc), message='Discovery failed')
