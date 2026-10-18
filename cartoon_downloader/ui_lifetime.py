"""Track browser documents without confusing a reload with application exit."""

import re
import threading
import time


class UiLifetime:
    def __init__(self, clock=time.monotonic, grace=5.0, lease=180.0):
        self.clock = clock
        self.grace = grace
        self.lease = lease
        self.lock = threading.Lock()
        self.sessions = {}
        self.empty_deadline = None
        self.enabled = False
        self.exit_requested = threading.Event()

    def arm(self):
        with self.lock:
            self.enabled = True
            self.empty_deadline = self.clock() + self.lease

    def update(self, session_id: str, action: str):
        if not isinstance(session_id, str) or not re.fullmatch(r'[a-zA-Z0-9-]{16,80}', session_id):
            raise ValueError('Invalid UI session')
        if action not in {'open', 'ping', 'close'}:
            raise ValueError('Invalid UI session action')
        with self.lock:
            now = self.clock()
            if action == 'open':
                self.sessions[session_id] = now
                self.empty_deadline = None
            elif action == 'ping':
                if session_id in self.sessions:
                    self.sessions[session_id] = now
            else:
                self.sessions.pop(session_id, None)
                if not self.sessions and self.empty_deadline is None:
                    self.empty_deadline = now + self.grace

    def should_stop(self):
        if self.exit_requested.is_set():
            return True
        with self.lock:
            if not self.enabled:
                return False
            now = self.clock()
            expired = [key for key, stamp in self.sessions.items() if now - stamp >= self.lease]
            for key in expired:
                del self.sessions[key]
            if self.sessions:
                return False
            if self.empty_deadline is None:
                self.empty_deadline = now + self.grace
            return now >= self.empty_deadline

    def defer_after_pause(self, seconds):
        """A suspended computer must not expire a still-open browser window."""
        with self.lock:
            self.sessions = {key: stamp + seconds for key, stamp in self.sessions.items()}
            if self.empty_deadline is not None:
                self.empty_deadline += seconds
