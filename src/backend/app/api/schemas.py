"""APIの入出力スキーマ（HTTP契約）。ドメインモデルとは分離し、変換はここで行う。"""
from __future__ import annotations
from typing import Literal, Optional

from pydantic import BaseModel, Field

from ..domain.models import Declaration, Hint, Image, Instrument, Point, Session
from ..services.tagging_service import HintInput


class PointIO(BaseModel):
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    status: Literal["visible", "estimated"] = "visible"

    def to_domain(self) -> Point:
        return Point(self.x, self.y, self.status)

    @classmethod
    def from_domain(cls, p: Optional[Point]) -> Optional["PointIO"]:
        return None if p is None else cls(x=p.x, y=p.y, status=p.status)


class InstrumentOut(BaseModel):
    instrument_uid: str
    name: str
    category_path: str
    category_levels: list[str]
    status: str

    @classmethod
    def of(cls, i: Instrument) -> "InstrumentOut":
        return cls(instrument_uid=i.instrument_uid, name=i.name, category_path=i.category_path,
                   category_levels=i.category_levels, status=i.status)


class SessionIn(BaseModel):
    operator: str = ""
    location: str = ""
    lighting: str = ""
    camera_model: str = ""
    notes: str = ""


class SessionOut(SessionIn):
    session_id: str
    started_at: str
    closed_at: Optional[str] = None

    @classmethod
    def of(cls, s: Session) -> "SessionOut":
        return cls(**s.__dict__)


class DeclarationItemIO(BaseModel):
    instrument_uid: str
    count: int = Field(ge=1, le=50, default=1)


class DeclarationIn(BaseModel):
    items: list[DeclarationItemIO] = []
    copy_from: Optional[str] = None


class DeclarationOut(BaseModel):
    declaration_id: str
    session_id: str
    items: list[DeclarationItemIO]
    mode: Literal["single", "multi"]
    total_count: int
    confirmed: bool
    confirmed_at: Optional[str]
    arrangement_no: int
    created_at: str
    copied_from: Optional[str]

    @classmethod
    def of(cls, d: Declaration) -> "DeclarationOut":
        return cls(declaration_id=d.declaration_id, session_id=d.session_id,
                   items=[DeclarationItemIO(instrument_uid=i.instrument_uid, count=i.count) for i in d.items],
                   mode=d.mode, total_count=d.total_count, confirmed=d.confirmed, confirmed_at=d.confirmed_at,
                   arrangement_no=d.arrangement_no, created_at=d.created_at, copied_from=d.copied_from)


class ImageOut(BaseModel):
    image_id: str
    declaration_id: str
    session_id: str
    arrangement_no: int
    width: int
    height: int
    content_type: str
    sha256: str
    captured_at: str
    meta: dict
    tag_status: Literal["untagged", "tagged"]
    tag_revision: int
    tagged_at: Optional[str]
    tagged_by: str
    file_url: str

    @classmethod
    def of(cls, i: Image) -> "ImageOut":
        d = {k: v for k, v in i.__dict__.items() if k != "path"}
        return cls(**d, file_url=f"/images/{i.image_id}/file")


class HintIn(BaseModel):
    instrument_uid: str
    hint_source: Literal["manual", "auto_center", "none"] = "manual"
    visible: bool = True
    center: Optional[PointIO] = None
    end_a: Optional[PointIO] = None
    end_b: Optional[PointIO] = None
    occluded: bool = False
    added_after_capture: bool = False

    def to_input(self) -> HintInput:
        return HintInput(instrument_uid=self.instrument_uid, hint_source=self.hint_source, visible=self.visible,
                         center=self.center.to_domain() if self.center else None,
                         end_a=self.end_a.to_domain() if self.end_a else None,
                         end_b=self.end_b.to_domain() if self.end_b else None,
                         occluded=self.occluded, added_after_capture=self.added_after_capture)


class HintOut(BaseModel):
    instrument_uid: str
    instance_no: int
    visible: bool
    hint_source: str
    hint_quality: Literal["full", "center_only", "none"]
    center: Optional[PointIO]
    end_a: Optional[PointIO]
    end_b: Optional[PointIO]
    occluded: bool
    added_after_capture: bool

    @classmethod
    def of(cls, h: Hint) -> "HintOut":
        return cls(instrument_uid=h.instrument_uid, instance_no=h.instance_no, visible=h.visible,
                   hint_source=h.hint_source, hint_quality=h.hint_quality,
                   center=PointIO.from_domain(h.center), end_a=PointIO.from_domain(h.end_a),
                   end_b=PointIO.from_domain(h.end_b), occluded=h.occluded,
                   added_after_capture=h.added_after_capture)


class TagsIn(BaseModel):
    hints: list[HintIn]
    tagged_by: str = ""


class IssueOut(BaseModel):
    code: str
    message: str
    instrument_uid: Optional[str] = None


class TagsOut(BaseModel):
    image_id: str
    hints: list[HintOut]
    errors: list[IssueOut] = []
    warnings: list[IssueOut] = []
