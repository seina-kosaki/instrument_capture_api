"""設定値の既定パスと明示上書きを検証する。"""
from pathlib import Path

from app.config import Settings


def test_settings_from_env_when_data_dir_not_set_uses_repo_data_and_legacy_source(monkeypatch) -> None:
    """既定ではrepo/dataを使い、旧src/dataを移行元として認識する。"""
    # Arrange
    monkeypatch.delenv("IC_DATA_DIR", raising=False)

    # Act
    settings = Settings.from_env()
    repository_root = Path(__file__).resolve().parents[3]

    # Assert
    assert settings.data_dir == repository_root / "data"
    assert settings.legacy_data_dir == repository_root / "src" / "data"


def test_settings_from_env_when_data_dir_is_set_disables_legacy_relocation(monkeypatch, tmp_path: Path) -> None:
    """明示した保存先を優先し、暗黙の旧データ移行を行わない。"""
    # Arrange
    monkeypatch.setenv("IC_DATA_DIR", str(tmp_path / "custom-data"))

    # Act
    settings = Settings.from_env()

    # Assert
    assert settings.data_dir == tmp_path / "custom-data"
    assert settings.legacy_data_dir is None