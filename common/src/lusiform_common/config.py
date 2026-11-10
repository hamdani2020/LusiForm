"""Shared base settings. Reads environment variables only; never touches a database."""

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseAppSettings(BaseSettings):
    """Settings common to api and worker. Subclass to add service-specific fields.

    Secrets are supplied by the environment (Secrets Manager in AWS, a git-ignored
    .env locally). Nothing here carries a default secret.
    """

    model_config = SettingsConfigDict(env_file=None, extra="ignore", frozen=True)

    service_name: str = Field(default="lusiform", min_length=1)
    environment: Literal["local", "staging", "prod"] = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    aws_region: str = "us-east-1"
