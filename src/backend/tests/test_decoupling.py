"""ポート差し替えで動くこと（疎結合の確認）: カタログを別実装に置換してもAPIが動く。"""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.config import Settings
from app.domain.models import Instrument
from app.main import create_app
from fastapi.testclient import TestClient

from .conftest import catalog_db


class InMemoryCatalog:
    _d = {"X-1": Instrument("X-1", "テスト器具", "テスト/器具")}

    def list(self, q=None, include_inactive=False):
        return list(self._d.values())

    def get(self, uid):
        return self._d.get(uid)


def test_swap_catalog(tmp_path: Path, catalog_db: Path) -> None:
    """明示注入したカタログを使い、既定SQLiteを開かずにAPIを構築する。"""
    # Arrange
    s = Settings(data_dir=tmp_path, catalog_db=catalog_db)

    # Act
    with TestClient(create_app(s, catalog=InMemoryCatalog(), clock=lambda: datetime(2026, 1, 1, tzinfo=ZoneInfo("Asia/Tokyo")))) as c:
        # Assert
        assert [i["instrument_uid"] for i in c.get("/instruments").json()] == ["X-1"]
        sid = c.post("/sessions", json={}).json()["session_id"]
        assert c.post(f"/sessions/{sid}/declarations", json={"items": [{"instrument_uid": "X-1"}]}).status_code == 201
