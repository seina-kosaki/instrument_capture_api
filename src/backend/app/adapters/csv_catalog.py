"""CSV 版 InstrumentCatalog（モック用）。

必須列は instrument_uid / name / category_path のみ。
本番の器具マスタCSV（status, end_a_definition 等の追加列）が来ても読めるよう、
未知の列は無視し、status 列があれば利用する（無ければ active）。
"""
from __future__ import annotations
import csv
import unicodedata
from pathlib import Path
from typing import Optional

from ..domain.models import Instrument

REQUIRED = ("instrument_uid", "name", "category_path")


def _norm(s: str) -> str:
    return unicodedata.normalize("NFKC", s).lower()


class CsvInstrumentCatalog:
    def __init__(self, path: Path):
        self._path = Path(path)
        self._items: dict[str, Instrument] = {}
        self.reload()

    def reload(self) -> None:
        items: dict[str, Instrument] = {}
        with open(self._path, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            missing = [c for c in REQUIRED if c not in (reader.fieldnames or [])]
            if missing:
                raise ValueError(f"器具CSVに必須列がありません: {missing}")
            for row in reader:
                uid = (row.get("instrument_uid") or "").strip()
                if not uid:
                    continue  # 未採番行は無視（登録処理の対象）
                if uid in items:
                    raise ValueError(f"instrument_uid が重複しています: {uid}")
                items[uid] = Instrument(
                    instrument_uid=uid,
                    name=(row.get("name") or "").strip(),
                    category_path=(row.get("category_path") or "").strip(),
                    status=(row.get("status") or "active").strip() or "active",
                )
        self._items = items

    def list(self, q: Optional[str] = None, include_inactive: bool = False) -> list[Instrument]:
        out = [i for i in self._items.values() if include_inactive or i.status == "active"]
        if q:
            nq = _norm(q)
            out = [i for i in out if nq in _norm(i.name) or nq in _norm(i.category_path) or nq in _norm(i.instrument_uid)]
        return out

    def get(self, uid: str) -> Optional[Instrument]:
        return self._items.get(uid)
