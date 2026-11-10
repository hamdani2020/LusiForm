# lusiform-common

Small internal package shared by `api/` and `worker/`:

- `BaseAppSettings`: environment-driven settings (Pydantic Settings). No secret defaults.
- `configure_logging`, `get_logger`, `bind_log_context`: structured JSON logs on stdout
  carrying `request_id`, `partner_id`, `user_id`, `project_id`. A redaction processor
  replaces secrets, credentials, and intake free text with `[REDACTED]`.

It must never import a database driver or touch the database.

Until Compose lands (foundation task 1.5), run the toolchain in a container:

```
docker build -t lusiform-uv-tools -f tools/uv.Dockerfile tools
docker run --rm -v "$PWD":/repo -w /repo/common lusiform-uv-tools \
  sh -c "uv run --frozen ruff check . && uv run --frozen mypy . && uv run --frozen pytest -q"
```

Swap `common` for `api` or `worker` to check those packages.
