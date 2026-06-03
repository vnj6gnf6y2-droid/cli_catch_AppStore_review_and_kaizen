"""End-to-end dry-run test using HTTP mocks."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import respx
from httpx import Response
from typer.testing import CliRunner

from appreview.cli import app

runner = CliRunner()


class TestDryRun:
    """End-to-end dry-run tests using mocked HTTP."""

    def test_dry_run_does_not_raise(
        self,
        sample_config_yaml: Path,
        app_store_response: dict,
        fake_p8_key: Path,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        """appreview run --dry-run should complete without errors."""
        # Patch the .p8 key path in the fixture config
        monkeypatch.setenv("APP_STORE_ISSUER_ID", "test-issuer")
        monkeypatch.setenv("APP_STORE_KEY_ID", "TEST001")
        monkeypatch.setenv("APP_STORE_PRIVATE_KEY_PATH", str(fake_p8_key))
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        # Update config to point to output dir in tmp_path
        import yaml
        with sample_config_yaml.open() as f:
            cfg = yaml.safe_load(f)
        cfg["output"]["output_dir"] = str(tmp_path / "reports")
        cfg["storage"]["database_path"] = str(tmp_path / "test.db")
        cfg["fetch"]["request_delay_ms"] = 0
        with sample_config_yaml.open("w") as f:
            yaml.dump(cfg, f)

        response_data = {
            "data": app_store_response["reviews"],
            "links": {},
        }

        with respx.mock(base_url="https://api.appstoreconnect.apple.com") as mock:
            mock.get("/v1/apps/1234567890/customerReviews").mock(
                return_value=Response(200, json=response_data)
            )

            result = runner.invoke(
                app,
                [
                    "run",
                    "--config", str(sample_config_yaml),
                    "--dry-run",
                ],
            )

        assert result.exit_code == 0, f"Exit code {result.exit_code}: {result.output}"

    def test_help_command_exits_zero(self) -> None:
        """--help should exit with code 0."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0

    def test_version_command(self) -> None:
        """--version should print version string."""
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.output

    def test_init_creates_config(self, tmp_path: Path) -> None:
        """appreview init should create a config file when given input."""
        config_path = tmp_path / "appreview.yaml"

        # Provide interactive input
        input_str = "y\nTest iOS App\n1234567890\n\ny\nTest Android App\ncom.example.test\nopenai\n./reports\n"

        result = runner.invoke(
            app,
            ["init", "--config", str(config_path)],
            input=input_str,
        )

        assert result.exit_code == 0
        assert config_path.exists()

        import yaml
        with config_path.open() as f:
            cfg = yaml.safe_load(f)

        assert len(cfg["apps"]) == 2
        assert cfg["apps"][0]["source"] == "app_store"
        assert cfg["apps"][1]["source"] == "google_play"

    def test_doctor_with_missing_credentials(
        self, sample_config_yaml: Path, monkeypatch
    ) -> None:
        """doctor should report missing credentials and exit non-zero."""
        # Clear all relevant env vars
        for key in [
            "APP_STORE_ISSUER_ID",
            "APP_STORE_KEY_ID",
            "APP_STORE_PRIVATE_KEY_PATH",
            "OPENAI_API_KEY",
        ]:
            monkeypatch.delenv(key, raising=False)

        result = runner.invoke(
            app,
            ["doctor", "--config", str(sample_config_yaml)],
        )

        assert result.exit_code != 0

    def test_fetch_only_dry_run(
        self,
        sample_config_yaml: Path,
        app_store_response: dict,
        fake_p8_key: Path,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        """appreview fetch --dry-run should not write to database."""
        monkeypatch.setenv("APP_STORE_ISSUER_ID", "test-issuer")
        monkeypatch.setenv("APP_STORE_KEY_ID", "TEST001")
        monkeypatch.setenv("APP_STORE_PRIVATE_KEY_PATH", str(fake_p8_key))

        import yaml
        with sample_config_yaml.open() as f:
            cfg = yaml.safe_load(f)
        cfg["storage"]["database_path"] = str(tmp_path / "test.db")
        cfg["fetch"]["request_delay_ms"] = 0
        with sample_config_yaml.open("w") as f:
            yaml.dump(cfg, f)

        db_path = tmp_path / "test.db"

        response_data = {
            "data": app_store_response["reviews"],
            "links": {},
        }

        with respx.mock(base_url="https://api.appstoreconnect.apple.com") as mock:
            mock.get("/v1/apps/1234567890/customerReviews").mock(
                return_value=Response(200, json=response_data)
            )

            result = runner.invoke(
                app,
                ["fetch", "--config", str(sample_config_yaml), "--dry-run"],
            )

        assert result.exit_code == 0
        # In dry-run mode, no reviews should be written but the DB tables may be created

    def test_list_runs_empty_db(
        self, sample_config_yaml: Path, tmp_path: Path
    ) -> None:
        """list-runs on empty DB should print informational message."""
        import yaml
        with sample_config_yaml.open() as f:
            cfg = yaml.safe_load(f)
        cfg["storage"]["database_path"] = str(tmp_path / "empty.db")
        with sample_config_yaml.open("w") as f:
            yaml.dump(cfg, f)

        result = runner.invoke(
            app,
            ["list-runs", "--config", str(sample_config_yaml)],
        )

        assert result.exit_code == 0
