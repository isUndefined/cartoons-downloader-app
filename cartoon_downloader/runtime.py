"""Versioned UI sections: unchanged history never accompanies progress updates."""

import hashlib
import json
import secrets
import threading
from collections import OrderedDict

from .catalog import catalog_snapshot, job_snapshot, page_number


class RuntimeSnapshots:
    def __init__(self, db, discovery):
        self.db = db
        self.discovery = discovery
        # Tokens from a previous application process must force a full refresh.
        self.epoch = secrets.token_hex(8)
        self.lock = threading.Lock()
        self.cache = OrderedDict()

    def _cached(self, key, build):
        if key not in self.cache:
            self.cache[key] = build()
            while len(self.cache) > 8:
                self.cache.popitem(last=False)
        self.cache.move_to_end(key)
        return self.cache[key]

    def snapshot(self, query: dict) -> dict:
        requested = {name: page_number(query, name + '_page')
                     for name in ('discovery', 'downloaded', 'failures')}
        with self.lock, self.db.connect() as con:
            # Revisions, counts and rows belong to the same SQLite read snapshot.
            con.execute('BEGIN')
            revisions = dict(con.execute('SELECT section,version FROM runtime_revisions'))
            catalog_token = f"{self.epoch}:{revisions['catalog']}:" + ':'.join(map(str, requested.values()))
            jobs_token = f"{self.epoch}:{revisions['jobs']}:{requested['failures']}"
            discovery = self.discovery.snapshot()
            discovery_token = self.epoch + ':' + hashlib.sha256(
                json.dumps(discovery, sort_keys=True).encode('utf-8')
            ).hexdigest()[:16]
            versions = {'catalog': catalog_token, 'jobs': jobs_token, 'discovery': discovery_token}
            response = {'versions': versions}
            if (query.get('catalog_version') or [None])[0] != catalog_token:
                response.update(self._cached(('catalog', catalog_token), lambda: catalog_snapshot(con, requested)))
            if (query.get('jobs_version') or [None])[0] != jobs_token:
                response['jobs'] = self._cached(('jobs', jobs_token), lambda: job_snapshot(con, requested['failures']))
            if (query.get('discovery_version') or [None])[0] != discovery_token:
                response['discovery'] = discovery
            return response
