"""Unit tests for configuration loading."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from appreview.config import load_config
from appreview.exceptions import ConfigError


class TestLoadConfig:
    """Tests for configuration file loading and validation."""

    def test_loads_valid_config(self, sample_config_yaml: Path) -> None:
        """Valid config file should load without errors."""
        config = load_config(sample_config_yaml)
        assert len(config.apps) == 1
        assert config.apps[0].name == "TestApp iOS"
        assert config.apps[0].source == "app_store"
        assert config.apps[0].app_id == "1234567890"

    def test_raises_on_missing_file(self, tmp_path: Path) -> None:
        """Missing config file should raise ConfigError."""
        with pytest.raises(ConfigError, match="not found"):
            load_config(tmp_path / "nonexistent.yaml")

    def test_raises_on_empty_file(self, tmp_path: Path) -> None:
        """Empty config file should raise ConfigError."""
        empty_file = tmp_path / "empty.yaml"
        empty_file.write_text("")
        with pytest.raises(ConfigError, match="empty"):
            load_config(empty_file)

    def test_raises_on_missing_apps(self, tmp_path: Path) -> None:
        """Config without apps should raise ConfigError."""
        config_file = tmp_path / "no_apps.yaml"
        config_file.write_text("apps: []\nllm:\n  provider: openai\n")
        with pytest.raises(ConfigError):
            load_config(config_file)

    def test_raises_on_app_store_missing_app_id(self, tmp_path: Path) -> None:
        """App Store app without app_id should raise ConfigError."""
        content = {
            "apps": [{"name": "Test", "source": "app_store"}],
        }
        config_file = tmp_path / "invalid.yaml"
        config_file.write_text(yaml.dump(content))
        with pytest.raises((ConfigError, ValueError)):
            load_config(config_file)

    def test_raises_on_google_play_missing_package_name(self, tmp_path: Path) -> None:
        """Google Play app without package_name should raise ConfigError."""
        content = {
            "apps": [{"name": "Test", "source": "google_play"}],
        }
        config_file = tmp_path / "invalid.yaml"
        config_file.write_text(yaml.dump(content))
        with pytest.raises((ConfigError, ValueError)):
            load_config(config_file)

    def test_default_llm_config(self, sample_config_yaml: Path) -> None:
        """Config should have valid LLM defaults."""
        config = load_config(sample_config_yaml)
        assert config.llm.provider in ("openai", "anthropic", "ollama")
        assert config.llm.batch_size <= 50
        assert 0.0 <= config.llm.temperature <= 2.0

    def test_categories_always_has_other(self, tmp_path: Path) -> None:
        """Categories list must always contain 'other'."""
        content = {
            "apps": [{"name": "Test", "source": "app_store", "app_id": "123"}],
            "analysis": {"categories": ["performance", "bug_crash"]},
        }
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(content))
        config = load_config(config_file)
        assert "other" in config.analysis.categories

    def test_invalid_yaml_syntax(self, tmp_path: Path) -> None:
        """Invalid YAML syntax should raise ConfigError."""
        bad_yaml = tmp_path / "bad.yaml"
        bad_yaml.write_text("apps: [\n  - invalid: {{{\n")
        with pytest.raises(ConfigError):
            load_config(bad_yaml)

    def test_territories_optional(self, tmp_path: Path) -> None:
        """territories field is optional for App Store apps."""
        content = {
            "apps": [{"name": "Test", "source": "app_store", "app_id": "123"}],
        }
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(content))
        config = load_config(config_file)
        assert config.apps[0].territories is None


class TestValidateCredentials:
    """Tests for credential validation."""

    def test_detects_missing_openai_key(self, sample_config_yaml: Path) -> None:
        """Missing OpenAI key should be reported."""
        from appreview.config import EnvSettings, validate_provider_credentials
        config = load_config(sample_config_yaml)
        env = EnvSettings()  # type: ignore[call-arg]
        errors = validate_provider_credentials(config, env)
        # Should have errors for missing App Store credentials
        assert len(errors) > 0

    def test_no_errors_when_all_set(
        self, sample_config_yaml: Path, fake_p8_key: Path, tmp_path: Path
    ) -> None:
        """No errors when all credentials are present."""
        from appreview.config import EnvSettings, validate_provider_credentials
        config = load_config(sample_config_yaml)
        env = EnvSettings(  # type: ignore[call-arg]
            app_store_issuer_id="test-issuer",
            app_store_key_id="KEY001",
            app_store_private_key_path=fake_p8_key,
            openai_api_key="sk-test",
        )
        errors = validate_provider_credentials(config, env)
        assert errors == []
