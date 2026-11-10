"""Minimal FastAPI app. Routing, middleware and config land in spec task 2."""

from fastapi import APIRouter, FastAPI

router = APIRouter(prefix="/api")


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness probe. No auth."""
    return {"status": "ok"}


def create_app() -> FastAPI:
    app = FastAPI(title="Lusiform API")
    app.include_router(router)
    return app


app = create_app()
