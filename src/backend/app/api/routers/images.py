from __future__ import annotations
from typing import Literal, Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from ..schemas import HintOut, ImageOut, IssueOut, TagsIn, TagsOut

router = APIRouter(prefix="/images", tags=["images"])


def _out(image_id, hints, result) -> TagsOut:
    return TagsOut(image_id=image_id, hints=[HintOut.of(h) for h in hints],
                   errors=[IssueOut(**i.__dict__) for i in result.errors],
                   warnings=[IssueOut(**i.__dict__) for i in result.warnings])


@router.get("", response_model=list[ImageOut])
def list_images(request: Request, session_id: Optional[str] = None, declaration_id: Optional[str] = None,
                tag_status: Optional[Literal["untagged", "tagged"]] = None, date: Optional[str] = None,
                limit: int = Query(200, le=1000), offset: int = 0):
    imgs = request.app.state.c.capture.list_images(session_id=session_id, declaration_id=declaration_id,
                                                   tag_status=tag_status, date=date, limit=limit, offset=offset)
    return [ImageOut.of(i) for i in imgs]


@router.get("/{image_id}", response_model=ImageOut)
def get_image(request: Request, image_id: str):
    return ImageOut.of(request.app.state.c.capture.get_image(image_id))


@router.get("/{image_id}/file")
def get_image_file(request: Request, image_id: str):
    c = request.app.state.c.capture
    img = c.get_image(image_id)
    return StreamingResponse(c.open_image(image_id), media_type=img.content_type,
                             headers={"Cache-Control": "private, max-age=3600"})


@router.get("/{image_id}/tags", response_model=TagsOut)
def get_tags(request: Request, image_id: str):
    hints = request.app.state.c.tagging.get_tags(image_id)
    return TagsOut(image_id=image_id, hints=[HintOut.of(h) for h in hints])


@router.put("/{image_id}/tags", response_model=TagsOut)
def put_tags(request: Request, image_id: str, body: TagsIn):
    hints, result = request.app.state.c.tagging.save(image_id, [h.to_input() for h in body.hints], body.tagged_by)
    return _out(image_id, hints, result)


@router.post("/{image_id}/tags/validate", response_model=TagsOut)
def validate_tags(request: Request, image_id: str, body: TagsIn):
    """保存せずに整合性チェックだけ行う（タグ付けUIのライブ検証用）。"""
    hints, result = request.app.state.c.tagging.validate(image_id, [h.to_input() for h in body.hints])
    return _out(image_id, hints, result)


@router.post("/{image_id}/tags/from-declaration", response_model=TagsOut)
def tags_from_declaration(request: Request, image_id: str, tagged_by: str = ""):
    hints, result = request.app.state.c.tagging.accept_declaration(image_id, tagged_by)
    return _out(image_id, hints, result)
