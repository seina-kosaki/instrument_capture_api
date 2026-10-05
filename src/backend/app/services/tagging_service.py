from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Optional

from ..domain.errors import Conflict, InvalidInput, NotFound, TagValidationFailed
from ..domain.models import Hint, Point
from ..domain.tag_validation import ValidationResult, validate_tags
from ..ports import InstrumentCatalog, MetadataStore


@dataclass
class HintInput:
    """クライアントから受け取るタグ。instance_no はサーバーが採番する。"""
    instrument_uid: str
    hint_source: str = "manual"
    visible: bool = True
    center: Optional[Point] = None
    end_a: Optional[Point] = None
    end_b: Optional[Point] = None
    occluded: bool = False
    added_after_capture: bool = False


class TaggingService:
    def __init__(self, store: MetadataStore, catalog: InstrumentCatalog, now: Callable[[], str]):
        self._store, self._catalog, self._now = store, catalog, now

    def _image_and_decl(self, image_id: str):
        img = self._store.get_image(image_id)
        if img is None:
            raise NotFound(f"画像が見つかりません: {image_id}")
        decl = self._store.get_declaration(img.declaration_id)
        assert decl is not None
        return img, decl

    @staticmethod
    def _number(inputs: list[HintInput]) -> list[Hint]:
        """点を打った順に、器具ごとの画像内通し番号を採番する（個体は区別しない方針）。"""
        counters: dict[str, int] = {}
        out: list[Hint] = []
        for h in inputs:
            counters[h.instrument_uid] = counters.get(h.instrument_uid, 0) + 1
            out.append(Hint(instrument_uid=h.instrument_uid, instance_no=counters[h.instrument_uid],
                            visible=h.visible, hint_source=("none" if not h.visible else h.hint_source),
                            center=h.center, end_a=h.end_a, end_b=h.end_b, occluded=h.occluded,
                            added_after_capture=h.added_after_capture))
        return out

    def get_tags(self, image_id: str) -> list[Hint]:
        self._image_and_decl(image_id)
        return self._store.list_hints(image_id)

    def validate(self, image_id: str, inputs: list[HintInput]) -> tuple[list[Hint], ValidationResult]:
        _, decl = self._image_and_decl(image_id)
        hints = self._number(inputs)
        known = [i.instrument_uid for i in self._catalog.list(include_inactive=True)]
        return hints, validate_tags(decl, hints, known)

    def save(self, image_id: str, inputs: list[HintInput], tagged_by: str = "") -> tuple[list[Hint], ValidationResult]:
        img, _ = self._image_and_decl(image_id)
        hints, result = self.validate(image_id, inputs)
        if not result.ok:
            raise TagValidationFailed("タグの整合性チェックに失敗しました", details={
                "errors": [i.__dict__ for i in result.errors], "warnings": [i.__dict__ for i in result.warnings]})
        self._store.replace_hints(image_id, hints)
        img.tag_status, img.tag_revision = "tagged", img.tag_revision + 1
        img.tagged_at, img.tagged_by = self._now(), tagged_by
        self._store.update_image(img)
        return hints, result

    def accept_declaration(self, image_id: str, tagged_by: str = "") -> tuple[list[Hint], ValidationResult]:
        """単体撮影用: 宣言をそのままラベルとして確定（点なし, hint_source=none）。"""
        _, decl = self._image_and_decl(image_id)
        if decl.mode != "single":
            raise Conflict("点なし保存は単体撮影（宣言=1器具1個）のみ可能です")
        uid = decl.items[0].instrument_uid
        return self.save(image_id, [HintInput(instrument_uid=uid, hint_source="none")], tagged_by)
