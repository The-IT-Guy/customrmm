from __future__ import annotations
from collections import defaultdict, deque
from time import time

class RateLimiter:
    def __init__(self, per_minute: int):
        self.per_minute = max(1, int(per_minute))
        self._hits = defaultdict(deque)  # key -> deque[timestamps]

    def allow(self, key: str) -> bool:
        now = time()
        q = self._hits[key]
        cutoff = now - 60.0
        while q and q[0] < cutoff:
            q.popleft()
        if len(q) >= self.per_minute:
            return False
        q.append(now)
        return True
