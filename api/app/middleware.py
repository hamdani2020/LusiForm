"""Request-id middleware (pure ASGI so log context is set and cleared reliably)."""

import time
import uuid

from lusiform_common import bind_log_context, clear_log_context, get_logger
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"

_log = get_logger("app.access")


class RequestIdMiddleware:
    """Generate a `request_id` per request.

    The id is always server-generated (a client-supplied header is ignored so it
    cannot inject content into logs). It is stored on `scope["state"]`, bound to
    the log context, and returned in the `X-Request-ID` response header.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        bind_log_context(request_id=request_id)

        status_code = 500
        started = time.perf_counter()

        async def send_with_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            _log.info(
                "request",
                method=scope["method"],
                path=scope["path"],
                status=status_code,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            clear_log_context()
