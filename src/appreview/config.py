"""Configuration management for appreview-insight.

Loads settings from appreview.yaml and environment variables.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseModel):
    """Configuration for a single app to monitor."""

    name: str
    source: Literal["app_store", "google_play"]
    app_id: str | None = None
    package_name: str | None = None
    territories: list[str] | None = None

    @model_validator(mode="after")
    def validate_source_fields(self) -> "AppConfig":
        """Ensure the correct identifier is provided for the source."""
        if self.source == "app_store" and not self.app_id:
            msg = f"App '{self.name}': app_id is required for app_store source"
            raise ValueError(msg)
        if self.source == "google_play" and not self.package_name:
            msg = f"App '{self.name}': package_name is required for google_play source"
            raise ValueError(msg)
        return self


class LLMConfig(BaseModel):
    """LLM provider configuration."""

    provider: Literal["openai", "anthropic", "ollama"] = "openai"
    classification_model: str = "gpt-4o-mini"
    suggestion_model: str = "gpt-4o"
    max_cost_usd_per_run: float = 5.00
    batch_size: int = Field(default=20, ge=1, le=50)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)


class AnalysisConfig(BaseModel):
    """Analysis pipeline configuration."""

    categories: list[str] = Field(
        default=[
            "performance",
            "ui_ux",
            "feature_request",
            "bug_crash",
            "billing",
            "auth",
            "notification",
            "other",
        ]
    )
    min_reviews_for_cluster: int = Field(default=3, ge=1)
    pii_masking: bool = True

    @field_validator("categories")
    @classmethod
    def categories_not_empty(cls, v: list[str]) -> list[str]:
        """Validate categories list is not empty and has 'other'."""
        if not v:
            msg = "categories must not be empty"
            raise ValueError(msg)
        if "other" not in v:
            v.append("other")
        return v


class OutputConfig(BaseModel):
    """Output format configuration."""

    formats: list[Literal["markdown", "json"]] = ["markdown", "json"]
    output_dir: Path = Path("./reports")
    filename_template: str = "{date}-{app_name}-report"


class StorageConfig(BaseModel):
    """Database storage configuration."""

    database_path: Path = Path("./appreview.db")
    anonymize_reviewers: bool = False


class FetchConfig(BaseModel):
    """Fetch behavior configuration."""

    since_days: int = Field(default=7, ge=1)
    request_delay_ms: int = Field(default=200, ge=0)


class AppReviewConfig(BaseModel):
    """Root configuration model for appreview.yaml."""

    apps: list[AppConfig] = Field(default_factory=list)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    fetch: FetchConfig = Field(default_factory=FetchConfig)

    @field_validator("apps")
    @classmethod
    def apps_not_empty(cls, v: list[AppConfig]) -> list[AppConfig]:
        """Validate at least one app is configured."""
        if not v:
            msg = "At least one app must be configured in the 'apps' section"
            raise ValueError(msg)
        return v


class EnvSettings(BaseSettings):
    """Environment variable settings for sensitive credentials."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_store_issuer_id: str | None = None
    app_store_key_id: str | None = None
    app_store_private_key_path: Path | None = None
    google_play_service_account_json: Path | None = None
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    ollama_base_url: str = "http://localhost:11434"


def load_config(config_path: Path) -> AppReviewConfig:
    """Load and validate configuration from a YAML file.

    Args:
        config_path: Path to the appreview.yaml file.

    Returns:
        Validated AppReviewConfig instance.

    Raises:
        ConfigError: If the file is missing or invalid.
    """
    from appreview.exceptions import ConfigError

    if not config_path.exists():
        msg = (
            f"Configuration file not found: {config_path}\n"
            "Run 'appreview init' to create a configuration file."
        )
        raise ConfigError(msg)

    try:
        with config_path.open() as f:
            raw: Any = yaml.safe_load(f)
    except yaml.YAMLError as e:
        msg = f"Failed to parse configuration file: {e}"
        raise ConfigError(msg) from e

    if raw is None:
        msg = "Configuration file is empty"
        raise ConfigError(msg)

    try:
        return AppReviewConfig.model_validate(raw)
    except Exception as e:
        msg = f"Invalid configuration: {e}"
        raise ConfigError(msg) from e


def load_env_settings() -> EnvSettings:
    """Load environment variable settings.

    Returns:
        EnvSettings instance with credential configuration.
    """
    return EnvSettings()  # type: ignore[call-arg]


def validate_provider_credentials(
    config: AppReviewConfig,
    env: EnvSettings,
) -> list[str]:
    """Validate that required credentials are present for configured providers.

    Args:
        config: Application configuration.
        env: Environment settings.

    Returns:
        List of warning/error messages. Empty if all credentials are present.
    """
    errors: list[str] = []

    # Check data source credentials
    sources = {app.source for app in config.apps}

    if "app_store" in sources:
        if not env.app_store_issuer_id:
            errors.append("APP_STORE_ISSUER_ID is not set")
        if not env.app_store_key_id:
            errors.append("APP_STORE_KEY_ID is not set")
        if not env.app_store_private_key_path:
            errors.append("APP_STORE_PRIVATE_KEY_PATH is not set")
        elif not env.app_store_private_key_path.exists():
            errors.append(
                f"APP_STORE_PRIVATE_KEY_PATH does not exist: "
                f"{env.app_store_private_key_path}"
            )

    if "google_play" in sources:
        if not env.google_play_service_account_json:
            errors.append("GOOGLE_PLAY_SERVICE_ACCOUNT_JSON is not set")
        elif not env.google_play_service_account_json.exists():
            errors.append(
                f"GOOGLE_PLAY_SERVICE_ACCOUNT_JSON does not exist: "
                f"{env.google_play_service_account_json}"
            )

    # Check LLM credentials
    provider = config.llm.provider
    if provider == "openai" and not env.openai_api_key:
        errors.append("OPENAI_API_KEY is not set (required for openai provider)")
    elif provider == "anthropic" and not env.anthropic_api_key:
        errors.append("ANTHROPIC_API_KEY is not set (required for anthropic provider)")

    return errors
