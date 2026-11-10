"""FastAPI app factory. All routes live under `/api`."""

from fastapi import APIRouter, FastAPI
from lusiform_common import configure_logging

from app.config import ApiSettings, get_settings
from app.middleware import RequestIdMiddleware

# Public router: no auth. Only /api/health (and, later, the auth callback).
public_router = APIRouter(prefix="/api")


@public_router.get("/health")
def health() -> dict[str, str]:
    """Liveness probe. No auth."""
    return {"status": "ok"}


def create_app(settings: ApiSettings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.service_name, settings.log_level)

    app = FastAPI(title="Lusiform API")
    app.add_middleware(RequestIdMiddleware)
    app.include_router(public_router)
    return app


app = create_app()
