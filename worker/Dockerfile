# Build context is the repo root (lusiform-common lives in ./common).
FROM hashicorp/terraform:1.10.5 AS terraform
FROM ghcr.io/terraform-linters/tflint:v0.54.0 AS tflint

FROM python:3.12-slim AS base
# Optional resolver override for networks where the build's default DNS is flaky.
# Applies to RUN steps only; nothing is persisted in the image.
ARG BUILD_DNS=""
COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /uvx /usr/local/bin/
COPY --from=terraform /bin/terraform /usr/local/bin/terraform
COPY --from=tflint /usr/local/bin/tflint /usr/local/bin/tflint
ENV UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/worker/.venv \
    UV_TOOL_DIR=/opt/uv-tools \
    UV_TOOL_BIN_DIR=/usr/local/bin \
    PATH=/app/worker/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
# Pinned Checkov, isolated from the worker's own environment.
RUN if [ -n "$BUILD_DNS" ]; then echo "nameserver $BUILD_DNS" > /etc/resolv.conf; fi \
    && uv tool install checkov==3.4.3
WORKDIR /app/worker
COPY common /app/common
COPY worker/pyproject.toml worker/uv.lock worker/.python-version ./
RUN if [ -n "$BUILD_DNS" ]; then echo "nameserver $BUILD_DNS" > /etc/resolv.conf; fi \
    && uv sync --frozen

FROM base AS dev
CMD ["python", "-m", "app.main"]

FROM base AS prod
COPY worker/ .
RUN useradd --system --uid 10001 lusiform
USER lusiform
CMD ["python", "-m", "app.main"]
