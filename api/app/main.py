"""FastAPI app factory. All routes live under `/api`."""

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from lusiform_common import configure_logging

from app.config import ApiSettings, get_settings
from app.errors import NotAuthorized, NotFound
from app.middleware import RequestIdMiddleware
from app.routers import me
from app.routers.admin import admin_router, operator_router

# Public router: no auth. Only /api/health (and, later, the auth callback).
public_router = APIRouter(prefix="/api")


@public_router.get("/health")
def health() -> dict[str, str]:
    """Liveness probe. No auth."""
    return {"status": "ok"}


async def _not_found(_request: Request, _exc: Exception) -> JSONResponse:
    # Same body for "missing" and "belongs to another partner": existence is not disclosed.
    return JSONResponse(status_code=404, content={"detail": "Not found"})


async def _forbidden(_request: Request, _exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=403, content={"detail": "Forbidden"})


def create_app(settings: ApiSettings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.service_name, settings.log_level)

    app = FastAPI(title="Lusiform API")
    app.add_middleware(RequestIdMiddleware)
    app.add_exception_handler(NotFound, _not_found)
    app.add_exception_handler(NotAuthorized, _forbidden)
    app.include_router(public_router)
    app.include_router(me.router)
    app.include_router(admin_router)
    app.include_router(operator_router)
    return app


app = create_app()
