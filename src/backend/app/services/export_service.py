"""解析用のエクスポート（1ヒント=1行のフラットな表）。pandas等でそのまま読める形にする。"""
from __future__ import annotations

from ..ports import InstrumentCatalog, MetadataStore


class ExportService:
    def __init__(self, store: MetadataStore, catalog: InstrumentCatalog):
        self._store, self._catalog = store, catalog

    def hint_rows(self, date: str | None = None) -> list[dict]:
        images = self._store.list_images(date=date, limit=10**9)
        hints = self._store.list_hints_for_images([i.image_id for i in images])
        rows: list[dict] = []
        for img in images:
            image_hints = hints.get(img.image_id, [])
            mode = "single" if len(image_hints) == 1 else "multi" if len(image_hints) > 1 else "unclassified"
            for h in image_hints:
                inst = self._catalog.get(h.instrument_uid)
                p = lambda pt, k: None if pt is None else getattr(pt, k)      # noqa: E731
                rows.append({
                    "image_id": img.image_id, "session_id": img.session_id, "declaration_id": img.declaration_id,
                    "arrangement_no": img.arrangement_no, "mode": mode, "captured_at": img.captured_at,
                    "image_width": img.width, "image_height": img.height,
                    "instrument_uid": h.instrument_uid, "instrument_name": inst.name if inst else "",
                    "category_path": inst.category_path if inst else "",
                    "instance_no": h.instance_no, "visible": h.visible, "hint_source": h.hint_source,
                    "hint_quality": h.hint_quality,
                    "center_x": p(h.center, "x"), "center_y": p(h.center, "y"), "center_status": p(h.center, "status"),
                    "end_a_x": p(h.end_a, "x"), "end_a_y": p(h.end_a, "y"),
                    "end_b_x": p(h.end_b, "x"), "end_b_y": p(h.end_b, "y"),
                    "occluded": h.occluded, "added_after_capture": h.added_after_capture,
                })
        return rows
