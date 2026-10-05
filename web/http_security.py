"""Bound worker count and authentication failures without trusting proxy headers."""
from collections import deque
from http.server import ThreadingHTTPServer
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


class BoundedHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, *args, max_workers=16, **kwargs):
        self.slots = threading.BoundedSemaphore(max_workers)
        self.login_limiter = LoginLimiter()
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def handle_error(self, request, client_address):
        pass  # Do not dump request context or auth headers into container logs.
