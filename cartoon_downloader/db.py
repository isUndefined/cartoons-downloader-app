from __future__ import annotations

import json
import math
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def _authorize_migration(action: int, *_details) -> int:
    # SQL files must not commit or roll back the runner's transaction.
    return sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_TRANSACTION else sqlite3.SQLITE_OK


DEFAULT_SETTINGS = {
    "target_pending": "10",
    "search_results_per_query": "6",
    "min_duration_minutes": "5",
    "max_results_per_channel": "2",
    "discovery_include_recent": "true",
    "download_folder": "downloads",
    "default_download_quality": "720",
    "theme": "dark",
    "device_folder": "/sdcard/Movies/CartoonDownloader",
    "ffmpeg_path": "",
    "adb_path": "",
    "ytdlp_path": "",
    "deno_path": "",
}

INTEGER_SETTINGS = {
    'target_pending': (1, 100),
    'search_results_per_query': (1, 30),
    'min_duration_minutes': (0, 600),
    'max_results_per_channel': (1, 20),
    'default_download_quality': (360, 1080),
}


def setting_integer(key, value):
    if isinstance(value, bool) or not re.fullmatch(r'[+-]?\d+', str(value)):
        raise ValueError(f'{key} must be a whole number')
    number = int(value)
    minimum, maximum = INTEGER_SETTINGS[key]
    if not minimum <= number <= maximum:
        raise ValueError(f'{key} must be between {minimum} and {maximum}')
    if key == 'default_download_quality' and number not in {360, 480, 720, 1080}:
        raise ValueError('Unsupported download quality')
    return number


def finite_weight(value):
    try:
        weight = float(value)
    except (ValueError, TypeError):
        raise ValueError('Hint and channel weights must be finite numbers') from None
    if not math.isfinite(weight):
        raise ValueError('Hint and channel weights must be finite numbers')
    return weight

DEFAULT_QUERIES = [
    "desene animate in romana",
    "desene animate romana",
    "povesti pentru copii romana",
    "desene pentru copii romana",
]

DEFAULT_ROMANIAN_HINTS = [
    ("în română", 25),
    ("in romana", 22),
    ("română", 18),
    ("romana", 16),
    ("dublat", 10),
    ("desene animate", 8),
]

DEFAULT_EXCLUDE_HINTS = [
    "reaction",
    "trailer",
    "gameplay",
    "shorts",
]


class Database:
    def __init__(self, db_path: Path, migrations_dir: Path):
        self.db_path = Path(db_path)
        self.migrations_dir = Path(migrations_dir)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()
        self._seed_defaults()

    def connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False, factory=ClosingConnection)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA busy_timeout=30000")
        return con

    @contextmanager
    def tx(self):
        con = self.connect()
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def _migrate(self) -> None:
        with self.tx() as con:
            con.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
            )
            applied = {r[0] for r in con.execute("SELECT version FROM schema_migrations")}
        for path in sorted(self.migrations_dir.glob("*.sql")):
            try:
                version = int(path.name.split("_", 1)[0])
            except ValueError:
                continue
            if version in applied:
                continue
            self._apply_migration(path, version)
            applied.add(version)

    def _apply_migration(self, path: Path, version: int) -> None:
        sql = path.read_text(encoding="utf-8")
        with self.tx() as con:
            # Python 3.13: legacy executescript() commits pending transactions.
            # PEP 249 mode keeps the SQL and its version record in one transaction.
            con.autocommit = False
            if con.execute("SELECT 1 FROM schema_migrations WHERE version=?", (version,)).fetchone():
                return
            con.set_authorizer(_authorize_migration)
            try:
                con.executescript(sql)
            except sqlite3.Error as exc:
                exc.add_note(f"Migration: {path.name}")
                raise
            finally:
                # The transaction owner must still be able to commit/roll back.
                con.set_authorizer(None)
            try:
                con.execute(
                    "INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)",
                    (version, path.name, now_iso()),
                )
            except sqlite3.Error as exc:
                exc.add_note(f"Migration version registration: {path.name}")
                raise

    def _seed_defaults(self):
        with self.tx() as con:
            for key, value in DEFAULT_SETTINGS.items():
                con.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (key, value))
            if con.execute("SELECT COUNT(*) FROM search_queries").fetchone()[0] == 0:
                con.executemany(
                    "INSERT INTO search_queries(query,enabled,position) VALUES(?,1,?)",
                    [(q, i) for i, q in enumerate(DEFAULT_QUERIES)],
                )
            if con.execute("SELECT COUNT(*) FROM hints WHERE kind='romanian'").fetchone()[0] == 0:
                con.executemany(
                    "INSERT INTO hints(kind,value,weight,enabled) VALUES('romanian',?,?,1)",
                    DEFAULT_ROMANIAN_HINTS,
                )
            if con.execute("SELECT COUNT(*) FROM hints WHERE kind='exclude'").fetchone()[0] == 0:
                con.executemany(
                    "INSERT INTO hints(kind,value,weight,enabled) VALUES('exclude',?,0,1)",
                    [(x,) for x in DEFAULT_EXCLUDE_HINTS],
                )

    def recover_interrupted_jobs(self):
        with self.tx() as con:
            interrupted = [r[0] for r in con.execute(
                "SELECT DISTINCT video_id FROM download_jobs WHERE status IN ('downloading','processing','transferring','verifying')"
            )]
            stamp = now_iso()
            con.execute(
                "UPDATE download_jobs SET status='failed', phase='interrupted', error='Application was closed while this job was active', last_message='Interrupted by application shutdown', finished_at=? WHERE status IN ('downloading','processing','transferring','verifying')",
                (stamp,),
            )
            if interrupted:
                placeholders = ','.join('?' for _ in interrupted)
                con.execute(
                    f"UPDATE videos SET status='pending',updated_at=? WHERE id IN ({placeholders}) AND status IN ('downloading','processing','transferring','verifying')",
                    (stamp, *interrupted),
                )

    def settings(self) -> dict:
        with self.connect() as con:
            base = {r["key"]: r["value"] for r in con.execute("SELECT key,value FROM settings")}
            base["search_queries"] = [
                dict(r) for r in con.execute("SELECT id,query,enabled,position FROM search_queries ORDER BY position,id")
            ]
            base["romanian_hints"] = [
                dict(r) for r in con.execute("SELECT id,value,weight,enabled FROM hints WHERE kind='romanian' ORDER BY id")
            ]
            base["exclude_hints"] = [
                dict(r) for r in con.execute("SELECT id,value,weight,enabled FROM hints WHERE kind='exclude' ORDER BY id")
            ]
            base["channel_rules"] = [dict(r) for r in con.execute("SELECT * FROM channel_rules ORDER BY rule,label,channel_key")]
        for key in INTEGER_SETTINGS:
            try:
                base[key] = setting_integer(key, base.get(key))
            except ValueError:
                # Allow the settings screen to repair values saved by older builds.
                base[key] = int(DEFAULT_SETTINGS[key])
        base["discovery_include_recent"] = str(base.get("discovery_include_recent", "true")).lower() == "true"
        return base

    def update_settings(self, payload: dict):
        if not isinstance(payload, dict):
            raise ValueError('Settings must be a JSON object')
        payload = payload.copy()
        for key in INTEGER_SETTINGS:
            if key in payload:
                payload[key] = setting_integer(key, payload[key])
        if 'theme' in payload and payload['theme'] not in {'light', 'dark'}:
            raise ValueError('Theme must be light or dark')
        if 'discovery_include_recent' in payload and not isinstance(payload['discovery_include_recent'], bool):
            raise ValueError('discovery_include_recent must be a boolean')
        for key in ('download_folder', 'device_folder', 'ffmpeg_path', 'adb_path', 'ytdlp_path', 'deno_path'):
            if key in payload and (not isinstance(payload[key], str) or '\x00' in payload[key]):
                raise ValueError(f'{key} must be a valid path string')
        for key in ('search_queries', 'romanian_hints', 'exclude_hints', 'channel_rules'):
            if key in payload and (not isinstance(payload[key], list) or any(
                not isinstance(item, (str, dict)) or (key == 'channel_rules' and not isinstance(item, dict))
                for item in payload[key]
            )):
                raise ValueError(f'{key} must be a list of valid entries')
        scalar_keys = {
            "target_pending", "search_results_per_query", "min_duration_minutes",
            "max_results_per_channel", "discovery_include_recent", "download_folder",
            "default_download_quality", "theme",
            "device_folder", "ffmpeg_path", "adb_path", "ytdlp_path", "deno_path",
        }
        with self.tx() as con:
            for key in scalar_keys:
                if key in payload:
                    value = payload[key]
                    if isinstance(value, bool):
                        value = "true" if value else "false"
                    con.execute(
                        "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (key, str(value)),
                    )

            if "search_queries" in payload:
                con.execute("DELETE FROM search_queries")
                rows = []
                for i, item in enumerate(payload["search_queries"]):
                    if isinstance(item, str):
                        query, enabled = item.strip(), 1
                    else:
                        query = str(item.get("query", "")).strip()
                        enabled = 1 if item.get("enabled", True) else 0
                    if query:
                        rows.append((query, enabled, i))
                con.executemany("INSERT INTO search_queries(query,enabled,position) VALUES(?,?,?)", rows)

            for key, kind in (("romanian_hints", "romanian"), ("exclude_hints", "exclude")):
                if key not in payload:
                    continue
                con.execute("DELETE FROM hints WHERE kind=?", (kind,))
                rows = []
                for item in payload[key]:
                    if isinstance(item, str):
                        value, weight, enabled = item.strip(), (10 if kind == "romanian" else 0), 1
                    else:
                        value = str(item.get("value", "")).strip()
                        weight = finite_weight(item.get("weight", 10 if kind == "romanian" else 0))
                        enabled = 1 if item.get("enabled", True) else 0
                    if value:
                        rows.append((kind, value, weight, enabled))
                con.executemany("INSERT INTO hints(kind,value,weight,enabled) VALUES(?,?,?,?)", rows)

            if "channel_rules" in payload:
                con.execute("DELETE FROM channel_rules")
                rows = []
                for item in payload["channel_rules"]:
                    channel_key = str(item.get("channel_key", "")).strip()
                    rule = str(item.get("rule", "")).strip()
                    if channel_key and rule in {"trusted", "blocked"}:
                        rows.append((channel_key, item.get("label"), rule, finite_weight(item.get("weight", 25))))
                con.executemany(
                    "INSERT INTO channel_rules(channel_key,label,rule,weight) VALUES(?,?,?,?)", rows
                )

    def list_videos(self, status: str | None = None) -> list[dict]:
        sql = "SELECT * FROM videos"
        params = []
        if status and status != "all":
            sql += " WHERE status=?"
            params.append(status)
        else:
            # Recommendations replaced by Refresh stay in SQLite for permanent
            # dedupe, but are intentionally hidden from the normal UI/API.
            sql += " WHERE status!='refreshed'"
        sql += " ORDER BY discovered_at DESC, score DESC, id DESC"
        with self.connect() as con:
            return [dict(r) for r in con.execute(sql, params)]

    def get_video(self, video_id: int) -> dict | None:
        with self.connect() as con:
            row = con.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone()
            return dict(row) if row else None

    def set_video_status(self, video_id: int, status: str):
        with self.tx() as con:
            if status == 'pending':
                con.execute("UPDATE videos SET status=?, unavailable_reason=NULL, updated_at=? WHERE id=?", (status, now_iso(), video_id))
            else:
                con.execute("UPDATE videos SET status=?, updated_at=? WHERE id=?", (status, now_iso(), video_id))

    def list_jobs(self) -> list[dict]:
        with self.connect() as con:
            rows = con.execute(
                """
                SELECT j.*, v.title, v.youtube_id, v.thumbnail_url, v.channel_name
                FROM download_jobs j JOIN videos v ON v.id=j.video_id
                WHERE j.status IN ('queued','downloading','processing','transferring','verifying')
                   OR j.id IN (
                       SELECT id FROM download_jobs
                       WHERE status NOT IN ('queued','downloading','processing','transferring','verifying')
                       ORDER BY id DESC LIMIT 200
                   )
                ORDER BY CASE WHEN j.status IN ('downloading','processing','transferring','verifying') THEN 0 WHEN j.status='queued' THEN 1 ELSE 2 END,
                         CASE WHEN j.status IN ('queued','downloading','processing','transferring','verifying') THEN j.position END,
                         j.id DESC
                """
            )
            return [dict(r) for r in rows]

    def list_devices(self) -> list[dict]:
        with self.connect() as con:
            return [dict(r) for r in con.execute("SELECT * FROM devices ORDER BY state='device' DESC,last_seen_at DESC")]
