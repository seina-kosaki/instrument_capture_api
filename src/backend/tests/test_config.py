"""設定値の既定パスと明示上書きを検証する。"""

from pathlib import Path

import pytest
from app.config import Settings


def test_settings_from_env_when_data_dir_not_set_uses_shared_data_and_master(monkeypatch: pytest.MonkeyPatch) -> None:
    """既定ではSPD直下の共有領域とSQLite器具マスタを使う。"""
    # Arrange
    monkeypatch.delenv("IC_DATA_DIR", raising=False)
    monkeypatch.delenv("IC_CATALOG_DB", raising=False)
    monkeypatch.delenv("IC_LEGACY_DATA_DIR", raising=False)

    # Act
    settings = Settings.from_env()
    repository_root = Path(__file__).resolve().parents[3]

    # Assert
    assert settings.data_dir == repository_root.parent / "shared_data"
    assert settings.catalog_db == repository_root.parent / "master" / "dataset.sqlite"
    assert settings.legacy_data_dir is None


def test_settings_from_env_when_catalog_db_is_set_uses_custom_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """環境変数でSQLite器具マスタのパスを上書きする。"""
    # Arrange
    catalog_path = tmp_path / "custom.sqlite"
    monkeypatch.setenv("IC_CATALOG_DB", str(catalog_path))

    # Act
    settings = Settings.from_env()

    # Assert
    assert settings.catalog_db == catalog_path


def test_settings_from_env_when_data_dir_is_set_disables_legacy_relocation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """明示した保存先を優先し、暗黙の旧データ移行を行わない。"""
    # Arrange
    monkeypatch.setenv("IC_DATA_DIR", str(tmp_path / "custom-data"))

    # Act
    settings = Settings.from_env()

    # Assert
    assert settings.data_dir == tmp_path / "custom-data"
    assert settings.legacy_data_dir is None


def test_settings_from_env_when_legacy_data_dir_is_set_uses_explicit_migration_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """明示された場合だけ旧データ移行元を設定する。"""
    # Arrange
    legacy_data_dir = tmp_path / "legacy-data"
    monkeypatch.delenv("IC_DATA_DIR", raising=False)
    monkeypatch.setenv("IC_LEGACY_DATA_DIR", str(legacy_data_dir))

    # Act
    settings = Settings.from_env()

    # Assert
    assert settings.legacy_data_dir == legacy_data_dir
