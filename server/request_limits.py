"""Bound anonymous OAuth registration before it can allocate persistent rows."""
from collections import Counter, deque
import math
import threading
import time

from starlette.responses import JSONResponse


class OAuthRegistrationLimitMiddleware:
    """Single-process ingress limit with bounded, expiring accounting.

    The supported hosted server uses one process. The catalog also enforces a
    durable total cap, serialized across processes; this limiter never writes
    one database row per attacker-controlled IP address.
    """

    def __init__(self, app, *, global_limit=300, client_limit=20,
                 window_seconds=3600, clock=time.monotonic):
        self.app = app
        self.global_limit = global_limit
        self.client_limit = client_limit
        self.window_seconds = window_seconds
        self.clock = clock
        self._requests = deque()
        self._clients = Counter()
        self._lock = threading.Lock()

    async def __call__(self, scope, receive, send):
        if (scope.get("type") != "http" or scope.get("method") != "POST"
                or scope.get("path", "").rstrip("/") != "/oauth/register"):
            await self.app(scope, receive, send)
            return
        # Use the server's peer address, never a client-supplied forwarded header.
        client = str((scope.get("client") or ("unknown",))[0])
        with self._lock:
            now = self.clock()
            while self._requests and self._requests[0][0] <= now - self.window_seconds:
                _, expired_client = self._requests.popleft()
                self._clients[expired_client] -= 1
                if not self._clients[expired_client]:
                    del self._clients[expired_client]
            blocked = (len(self._requests) >= self.global_limit
                       or self._clients[client] >= self.client_limit)
            retry_after = max(1, math.ceil(self.window_seconds))
            if not blocked:
                self._requests.append((now, client))
                self._clients[client] += 1
        if blocked:
            response = JSONResponse(
                {"error": "rate_limit_exceeded"}, status_code=429,
                headers={"Retry-After": str(retry_after), "Cache-Control": "no-store"})
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
