"""Typed API settings, loaded from the environment only.

No secret has a default here. Real values come from Secrets Manager in AWS or a
git-ignored `.env` locally (see `.env.example`).
"""

from functools import lru_cache

from lusiform_common import BaseAppSettings
from pydantic import Field, SecretStr


class ApiSettings(BaseAppSettings):
    """Settings for the API service."""

    service_name: str = Field(default="lusiform-api", min_length=1)

    # Connection string is a secret (it embeds the password).
    database_url: SecretStr | None = None

    # Cognito (used by auth in task 5). Not secrets.
    cognito_region: str | None = None
    cognito_user_pool_id: str | None = None
    cognito_app_client_id: str | None = None


@lru_cache
def get_settings() -> ApiSettings:
    return ApiSettings()
