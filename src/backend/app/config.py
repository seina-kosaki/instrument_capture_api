"""設定。環境変数から読む（コンポジションルートでのみ使用）。"""
from __future__ import annotations
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    catalog_csv: Path
    legacy_data_dir: Path | None = None
    camera_param_yaml: Path | None = None
    camera_id_yaml: Path | None = None
    camera_name: str | None = None
    camera_buffer_name: str = "color"
    timezone: str = "Asia/Tokyo"
    cors_origins: tuple[str, ...] = ("http://127.0.0.1:5173", "http://localhost:5173")
    # カバレッジ目標（配置数ベース）。器具ごと
    target_single_arrangements: int = 10
    target_multi_arrangements: int = 10
    max_upload_mb: int = 20
    save_debug_images: bool = True      # タグ保存時に、セッションバンドル内のdebug/へ生成画像を保存

    @classmethod
    def from_env(cls) -> "Settings":
        root = Path(__file__).resolve().parents[3]
        configured_data_dir = os.environ.get("IC_DATA_DIR")
        origins = os.environ.get("IC_CORS_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173")
        return cls(
            data_dir=Path(configured_data_dir) if configured_data_dir else root / "data",
            catalog_csv=Path(os.environ.get("IC_CATALOG_CSV", root / "src" / "master" / "instruments_mock.csv")),
            legacy_data_dir=None if configured_data_dir else root / "src" / "data",
            camera_param_yaml=Path(os.environ.get("IC_CAMERA_PARAM_YAML", root / "src" / "config" / "hardware" / "camera_param.yaml")),
            camera_id_yaml=Path(os.environ.get("IC_CAMERA_ID_YAML", root / "src" / "config" / "hardware" / "camera_id.yaml")),
            camera_name=os.environ.get("IC_CAMERA_NAME"),
            camera_buffer_name=os.environ.get("IC_CAMERA_BUFFER", "color"),
            timezone=os.environ.get("IC_TZ", "Asia/Tokyo"),
            cors_origins=tuple(o.strip() for o in origins.split(",") if o.strip()),
            target_single_arrangements=int(os.environ.get("IC_TARGET_SINGLE", 10)),
            target_multi_arrangements=int(os.environ.get("IC_TARGET_MULTI", 10)),
            max_upload_mb=int(os.environ.get("IC_MAX_UPLOAD_MB", 20)),
            save_debug_images=os.environ.get("IC_SAVE_DEBUG_IMAGES", "1").lower() in ("1", "true", "yes"),
        )
