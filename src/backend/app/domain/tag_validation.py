"""タグ（InstanceHint）の整合性チェック。純粋関数。

エラー  : 保存を拒否する
警告    : 保存はするが、画面に表示して確認を促す
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import Iterable

from .models import Declaration, Hint, Point

CLOSE_DIFFERENT = 0.02   # 別器具の中心がこれ未満で近接 → 取り違えの疑い
CLOSE_SAME = 0.01        # 同一器具の中心が重複
ENDS_COINCIDE = 0.005


@dataclass
class Issue:
    code: str
    message: str
    instrument_uid: str | None = None


@dataclass
class ValidationResult:
    errors: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _points(h: Hint) -> list[Point]:
    return [p for p in (h.center, h.end_a, h.end_b) if p is not None]


def _dist(a: Point, b: Point) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def validate_tags(declaration: Declaration, hints: list[Hint], known_uids: Iterable[str]) -> ValidationResult:
    r = ValidationResult()
    known = set(known_uids)
    declared = {i.instrument_uid for i in declaration.items}

    for h in hints:
        uid = h.instrument_uid
        if uid not in known:
            r.errors.append(Issue("UNKNOWN_INSTRUMENT", f"マスタに存在しない器具です: {uid}", uid))
            continue
        for p in _points(h):
            if not (0.0 <= p.x <= 1.0 and 0.0 <= p.y <= 1.0):
                r.errors.append(Issue("POINT_OUT_OF_RANGE", "点が画像範囲外です", uid))
                break
        if not h.visible:
            if _points(h):
                r.errors.append(Issue("INVISIBLE_WITH_POINTS", "見えない器具に点は付けられません", uid))
        elif h.hint_source == "none":
            if h.center is not None:
                r.errors.append(Issue("NONE_WITH_POINTS", "hint_source=none では点を指定できません", uid))
            if not (declaration.mode == "single" and len(hints) == 1):
                r.errors.append(Issue("NONE_NOT_ALLOWED", "点なし保存は単体撮影（宣言=1器具1個）のみ可能です", uid))
        else:
            if h.center is None:
                r.errors.append(Issue("CENTER_REQUIRED", "中心点は必須です", uid))
        if uid not in declared and not h.added_after_capture:
            r.errors.append(Issue("UNDECLARED_INSTRUMENT", "宣言外の器具です（added_after_capture を指定してください）", uid))
        if h.added_after_capture:
            r.warnings.append(Issue("ADDED_AFTER_CAPTURE", "撮影後に追加された器具です", uid))

        # 幾何チェック
        if h.center and h.end_a and h.end_b:
            a, b, c = h.end_a, h.end_b, h.center
            ab2 = (b.x - a.x) ** 2 + (b.y - a.y) ** 2
            if ab2 ** 0.5 < ENDS_COINCIDE:
                r.warnings.append(Issue("ENDS_COINCIDE", "両端の点がほぼ同じ位置です", uid))
            else:
                t = ((c.x - a.x) * (b.x - a.x) + (c.y - a.y) * (b.y - a.y)) / ab2
                if not (0.0 < t < 1.0):
                    r.warnings.append(Issue("CENTER_NOT_BETWEEN_ENDS", "中心点が両端の間にありません", uid))

    # 個数チェック（宣言個数 = 宣言分のタグ数。見えない器具も1件として数える）
    for item in declaration.items:
        n = sum(1 for h in hints if h.instrument_uid == item.instrument_uid and not h.added_after_capture)
        if n != item.count:
            r.errors.append(Issue("COUNT_MISMATCH", f"宣言{item.count}個に対しタグが{n}個です", item.instrument_uid))

    # 近接チェック（取り違え・二重打ちの検知）
    centers = [h for h in hints if h.center is not None]
    for i in range(len(centers)):
        for j in range(i + 1, len(centers)):
            a, b = centers[i], centers[j]
            d = _dist(a.center, b.center)  # type: ignore[arg-type]
            if a.instrument_uid == b.instrument_uid and d < CLOSE_SAME:
                r.warnings.append(Issue("DUPLICATE_POINT", "同一器具の中心点がほぼ重なっています", a.instrument_uid))
            elif a.instrument_uid != b.instrument_uid and d < CLOSE_DIFFERENT:
                r.warnings.append(Issue("CLOSE_POINTS", f"別の器具の中心点が近接しています（{a.instrument_uid} / {b.instrument_uid}）"))
    return r
