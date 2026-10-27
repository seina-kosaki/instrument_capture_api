"""ドメインモデル。フレームワーク・DB・ファイルシステムに依存しない。"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

PointStatus = str   # "visible" | "estimated"
HintSource = str    # "manual" | "auto_center" | "none"
TagStatus = str     # "untagged" | "tagged"


@dataclass(frozen=True)
class Instrument:
    instrument_uid: str
    name: str
    category_path: str
    status: str = "active"

    @property
    def category_levels(self) -> list[str]:
        return [p for p in self.category_path.split("/") if p]


@dataclass
class Session:
    session_id: str
    started_at: str
    closed_at: Optional[str] = None
    operator: str = ""
    location: str = ""
    lighting: str = ""
    camera_model: str = ""
    notes: str = ""


@dataclass(frozen=True)
class DeclarationItem:
    instrument_uid: str
    instrument_name: str = ""


@dataclass
class Declaration:
    declaration_id: str
    session_id: str
    items: list[DeclarationItem]
    created_at: str
    confirmed: bool = False
    confirmed_at: Optional[str] = None
    arrangement_no: int = 1
    copied_from: Optional[str] = None

    @property
    def contains_instrument(self, uid: str) -> bool:
        """器具が撮影候補に含まれるか判定する。"""
        return any(item.instrument_uid == uid for item in self.items)


@dataclass
class Image:
    """RGB画像を正本として、任意の深度画像を同じ撮影に関連付ける。

    Note:
        depth_pathがNoneの場合は深度未取得であり、既存のRGB画像として扱う。
    """

    image_id: str
    declaration_id: str
    session_id: str
    arrangement_no: int
    path: str
    sha256: str
    width: int
    height: int
    content_type: str
    captured_at: str
    meta: dict = field(default_factory=dict)
    tag_status: TagStatus = "untagged"
    tag_revision: int = 0
    tagged_at: Optional[str] = None
    tagged_by: str = ""
    camera_name: str = "unknown"
    camera_status: str = "unknown"
    location: str = ""
    depth_path: str | None = None


@dataclass(frozen=True)
class Point:
    """画像サイズで正規化した座標（0.0-1.0）。表示解像度に依存しない。"""
    x: float
    y: float
    status: PointStatus = "visible"


@dataclass
class Hint:
    instrument_uid: str
    instance_no: int
    visible: bool = True
    hint_source: HintSource = "manual"
    center: Optional[Point] = None
    end_a: Optional[Point] = None
    end_b: Optional[Point] = None
    occluded: bool = False
    added_after_capture: bool = False

    @property
    def hint_quality(self) -> str:
        if self.center is None:
            return "none"
        return "full" if (self.end_a and self.end_b) else "center_only"
