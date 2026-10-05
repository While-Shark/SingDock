"""Bound worker count and authentication failures without trusting proxy headers."""
from collections import deque
import threading
import time


class LoginLimiter:
    def __init__(self, clock=time.monotonic, limit=10, window=60):
        self.clock, self.limit, self.window = clock, limit, window
        self.failures = {}
        self.total = deque()
        self.lock = threading.Lock()

    def authenticate(self, peer, valid):
        with self.lock:
            now = self.clock()
            cutoff = now - self.window
            while self.total and self.total[0] <= cutoff:
                self.total.popleft()
            for key in list(self.failures):
                bucket = self.failures[key]
                while bucket and bucket[0] <= cutoff:
                    bucket.popleft()
                if not bucket:
                    del self.failures[key]
            bucket = self.failures.get(peer, deque())
            if len(bucket) >= self.limit or len(self.total) >= 100:
                return 429
            if valid:
                return 200
            if peer not in self.failures:
                if len(self.failures) >= 1024:
                    return 429
                self.failures[peer] = bucket
            bucket.append(now)
            self.total.append(now)
            return 401
