from fastapi import FastAPI
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.auth_api import router as auth_router
from app.broker_operations_api import router as broker_operations_router
from app.config import settings
from app.demo_accounts import DemoAccountRegistry
from app.health import router as health_router
from app.lane_api import router as lane_router
from app.observability import RequestObservabilityMiddleware, configure_logging
from app.rate_estimation_api import router as rate_estimation_router
from app.recommendation_api import router as recommendation_router
from app.shared_carrier_pool_api import router as shared_carrier_pool_router

_MAX_TOKEN_REQUEST_BYTES = 16_384


class OidcTokenBodyLimitMiddleware:
    def __init__(self, app, max_bytes: int = _MAX_TOKEN_REQUEST_BYTES):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if (
            scope.get("type") != "http"
            or scope.get("method") != "POST"
            or scope.get("path") != "/oidc/token"
        ):
            await self.app(scope, receive, send)
            return

        content_lengths = [
            value for name, value in scope.get("headers", []) if name.lower() == b"content-length"
        ]
        if len(content_lengths) > 1:
            await self._reject(send)
            return
        content_length = content_lengths[0] if content_lengths else None
        if content_length is not None:
            if not content_length or not all(48 <= byte <= 57 for byte in content_length):
                await self._reject(send)
                return
            if int(content_length) > self.max_bytes:
                await self._reject(send)
                return

        chunks: list[bytes] = []
        total = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                continue
            chunk = message.get("body", b"")
            total += len(chunk)
            if total > self.max_bytes:
                await self._reject(send)
                return
            chunks.append(chunk)
            if not message.get("more_body", False):
                break

        delivered = False

        async def replay_receive():
            nonlocal delivered
            if delivered:
                return {"type": "http.disconnect"}
            delivered = True
            return {"type": "http.request", "body": b"".join(chunks), "more_body": False}

        await self.app(scope, replay_receive, send)

    async def _reject(self, send):
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [(b"content-type", b"text/plain; charset=utf-8")],
            }
        )
        await send({"type": "http.response.body", "body": b"request body is too large"})


def create_app() -> FastAPI:
    configure_logging()
    application = FastAPI(
        title="Carrier Pool API",
        version="0.1.0",
        docs_url="/docs" if settings.demo_mode else None,
        redoc_url="/redoc" if settings.demo_mode else None,
        openapi_url="/openapi.json" if settings.demo_mode else None,
    )
    if not settings.demo_mode:
        application.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=[
                host.strip() for host in settings.allowed_hosts.split(",") if host.strip()
            ],
        )
    application.add_middleware(OidcTokenBodyLimitMiddleware)
    application.state.demo_accounts = DemoAccountRegistry()
    application.add_middleware(RequestObservabilityMiddleware)
    application.include_router(health_router)
    application.include_router(auth_router)
    application.include_router(lane_router)
    application.include_router(recommendation_router)
    application.include_router(rate_estimation_router)
    application.include_router(broker_operations_router)
    application.include_router(shared_carrier_pool_router)
    return application


app = create_app()
