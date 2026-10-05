"""取得状況の集計。常に元データから都度計算する（集計値は保存しない）。

主指標は「配置数」（同じ配置の連写は多様性が増えないため、枚数より配置数を重視）。
"""
from __future__ import annotations
from collections import defaultdict
from typing import Optional

from ..ports import InstrumentCatalog, MetadataStore


class StatsService:
    def __init__(self, store: MetadataStore, catalog: InstrumentCatalog, target_single: int, target_multi: int):
        self._store, self._catalog = store, catalog
        self._ts, self._tm = target_single, target_multi

    def _per_instrument(self, date: Optional[str]) -> dict:
        images = self._store.list_images(date=date, limit=10**9)
        decls = {d.declaration_id: d for d in self._store.list_declarations()}
        hints = self._store.list_hints_for_images([i.image_id for i in images])
        acc = defaultdict(lambda: {"images": 0, "single_images": 0, "multi_images": 0, "tagged_images": 0,
                                   "instances": 0, "occluded": 0,
                                   "_arr_single": set(), "_arr_multi": set(), "_sessions": set()})
        for img in images:
            d = decls[img.declaration_id]
            arr = (img.declaration_id, img.arrangement_no)
            for item in d.items:
                a = acc[item.instrument_uid]
                a["images"] += 1
                a[f"{d.mode}_images"] += 1
                a[f"_arr_{d.mode}"].add(arr)
                a["_sessions"].add(img.session_id)
                if img.tag_status == "tagged":
                    a["tagged_images"] += 1
            for h in hints.get(img.image_id, []):
                if h.visible:
                    acc[h.instrument_uid]["instances"] += 1
                    acc[h.instrument_uid]["occluded"] += int(h.occluded)
        return acc, images

    def instruments_table(self, date: Optional[str] = None) -> tuple[list[dict], list]:
        acc, images = self._per_instrument(date)
        rows = []
        for inst in self._catalog.list(include_inactive=True):
            a = acc.get(inst.instrument_uid)
            single_arr = len(a["_arr_single"]) if a else 0
            multi_arr = len(a["_arr_multi"]) if a else 0
            done = min(single_arr, self._ts) + min(multi_arr, self._tm)
            rows.append({
                "instrument_uid": inst.instrument_uid, "name": inst.name, "category_path": inst.category_path,
                "images": a["images"] if a else 0,
                "single_images": a["single_images"] if a else 0, "multi_images": a["multi_images"] if a else 0,
                "tagged_images": a["tagged_images"] if a else 0,
                "instances": a["instances"] if a else 0, "occluded": a["occluded"] if a else 0,
                "single_arrangements": single_arr, "multi_arrangements": multi_arr,
                "sessions": len(a["_sessions"]) if a else 0,
                "achievement": round(done / (self._ts + self._tm), 3) if (self._ts + self._tm) else 0.0,
            })
        return rows, images

    def coverage(self) -> dict:
        rows, images = self.instruments_table(None)
        return {
            "targets": {"single_arrangements": self._ts, "multi_arrangements": self._tm},
            "total_images": len(images),
            "overall_achievement": round(sum(r["achievement"] for r in rows) / len(rows), 3) if rows else 0.0,
            "instruments": rows,
            "next_to_shoot": [r["instrument_uid"] for r in sorted(rows, key=lambda r: r["achievement"])[:5] if r["achievement"] < 1],
        }

    def daily(self, date: str) -> dict:
        rows, images = self.instruments_table(date)
        arrangements = {(i.declaration_id, i.arrangement_no) for i in images}
        return {
            "date": date,
            "images": len(images),
            "tagged_images": sum(1 for i in images if i.tag_status == "tagged"),
            "untagged_images": [i.image_id for i in images if i.tag_status != "tagged"],
            "arrangements": len(arrangements),
            "sessions": sorted({i.session_id for i in images}),
            "instruments": [r for r in rows if r["images"] > 0],
        }
