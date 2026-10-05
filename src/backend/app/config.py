"""設定。環境変数から読む（コンポジションルートでのみ使用）。"""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    catalog_csv: Path
    timezone: str = "Asia/Tokyo"
    cors_origins: tuple[str, ...] = ("*",)
    # カバレッジ目標（配置数ベース）。器具ごと
    target_single_arrangements: int = 10
    target_multi_arrangements: int = 10
    max_upload_mb: int = 20

    @classmethod
    def from_env(cls) -> "Settings":
        root = Path(__file__).resolve().parents[2]
        origins = os.environ.get("IC_CORS_ORIGINS", "*")
        return cls(
            data_dir=Path(os.environ.get("IC_DATA_DIR", root / "data")),
            catalog_csv=Path(os.environ.get("IC_CATALOG_CSV", root / "master" / "instruments_mock.csv")),
            timezone=os.environ.get("IC_TZ", "Asia/Tokyo"),
            cors_origins=tuple(o.strip() for o in origins.split(",") if o.strip()),
            target_single_arrangements=int(os.environ.get("IC_TARGET_SINGLE", 10)),
            target_multi_arrangements=int(os.environ.get("IC_TARGET_MULTI", 10)),
            max_upload_mb=int(os.environ.get("IC_MAX_UPLOAD_MB", 20)),
        )
