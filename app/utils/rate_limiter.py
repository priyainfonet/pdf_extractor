"""
Lightweight in-memory rate limiter. No Redis, no external package — just
a dict of sliding windows per key, guarded by a lock. Fine for a single
dev/small-deployment server; if you ever run multiple server processes
behind a load balancer, this stops being accurate across processes and
you'd want a Redis-backed limiter instead (same call-site shape, so the
swap is contained to this file).

Usage as a FastAPI dependency:

    @router.post("/login", dependencies=[Depends(rate_limit("login", max_requests=5, window_seconds=60))])
"""

import time
import threading
from collections import defaultdict
from fastapi import Request, HTTPException

_lock = threading.Lock()
_hits: dict[str, list[float]] = defaultdict(list)


def rate_limit(bucket: str, max_requests: int, window_seconds: int):
    """Returns a FastAPI dependency that rate-limits by client IP, scoped
    to `bucket` (so /login and /register have independent limits even
    from the same IP)."""

    def dependency(request: Request):
        client_ip = request.client.host if request.client else "unknown"
        key = f"{bucket}:{client_ip}"
        now = time.monotonic()
        window_start = now - window_seconds

        with _lock:
            hits = _hits[key]
            # Drop timestamps outside the current window.
            while hits and hits[0] < window_start:
                hits.pop(0)

            if len(hits) >= max_requests:
                retry_after = int(window_seconds - (now - hits[0])) + 1
                raise HTTPException(
                    status_code=429,
                    detail="Too many requests. Please wait a moment and try again.",
                    headers={"Retry-After": str(retry_after)},
                )

            hits.append(now)

    return dependency
