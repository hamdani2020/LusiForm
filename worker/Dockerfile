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

# Pinned tflint AWS ruleset, installed with tflint's own signature-checking `--init` so
# tflint never downloads a plugin at run time. The version is also recorded in a template's
# template.json, and a test fails if the two drift.
ARG TFLINT_RULESET_AWS_VERSION=0.50.0
ENV TFLINT_PLUGIN_DIR=/opt/tflint-plugins
RUN if [ -n "$BUILD_DNS" ]; then echo "nameserver $BUILD_DNS" > /etc/resolv.conf; fi \
    && mkdir -p "$TFLINT_PLUGIN_DIR" /tmp/tflint-init \
    && printf 'plugin "aws" {\n  enabled = true\n  version = "%s"\n  source  = "github.com/terraform-linters/tflint-ruleset-aws"\n}\n' "$TFLINT_RULESET_AWS_VERSION" > /tmp/tflint-init/.tflint.hcl \
    && tflint --init --chdir /tmp/tflint-init \
    && rm -rf /tmp/tflint-init

FROM base AS dev
CMD ["python", "-m", "app.main"]

FROM base AS prod
COPY worker/ .
RUN useradd --system --uid 10001 lusiform
USER lusiform
CMD ["python", "-m", "app.main"]
