# Build context is the repo root (lusiform-common lives in ./common).
FROM python:3.12-slim AS base
# Optional resolver override for networks where the build's default DNS is flaky.
# Applies to RUN steps only; nothing is persisted in the image.
ARG BUILD_DNS=""
COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /uvx /usr/local/bin/
ENV UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/api/.venv \
    PATH=/app/api/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app/api
# lusiform-common is an editable path dependency (../common).
COPY common /app/common
COPY api/pyproject.toml api/uv.lock api/.python-version ./
RUN if [ -n "$BUILD_DNS" ]; then echo "nameserver $BUILD_DNS" > /etc/resolv.conf; fi \
    && uv sync --frozen

FROM base AS dev
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

FROM base AS prod
COPY api/ .
RUN useradd --system --uid 10001 lusiform
USER lusiform
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
