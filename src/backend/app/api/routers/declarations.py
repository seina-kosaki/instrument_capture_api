from __future__ import annotations
import json

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from ...domain.errors import InvalidInput
from ..schemas import DeclarationOut, ImageOut

router = APIRouter(prefix="/declarations", tags=["declarations"])
CAMERA_CONTENT_TYPE = "image/jpeg"


@router.get("/{declaration_id}", response_model=DeclarationOut)
def get_declaration(request: Request, declaration_id: str):
    return DeclarationOut.of(request.app.state.c.capture.get_declaration(declaration_id))


@router.post("/{declaration_id}/confirm", response_model=DeclarationOut)
def confirm(request: Request, declaration_id: str):
    return DeclarationOut.of(request.app.state.c.capture.confirm_declaration(declaration_id))


@router.post("/{declaration_id}/rearrange", response_model=DeclarationOut)
def rearrange(request: Request, declaration_id: str):
    return DeclarationOut.of(request.app.state.c.capture.rearrange(declaration_id))


@router.post("/{declaration_id}/images", response_model=ImageOut, status_code=201)
async def upload_image(request: Request, declaration_id: str, file: UploadFile = File(...), meta: str = Form("{}")):
    try:
        meta_obj = json.loads(meta)
        if not isinstance(meta_obj, dict):
            raise ValueError
    except ValueError:
        raise InvalidInput("meta はJSONオブジェクトで指定してください")
    data = await file.read()
    return ImageOut.of(request.app.state.c.capture.add_image(declaration_id, data, file.content_type or "", meta_obj))


@router.post("/{declaration_id}/capture", response_model=ImageOut, status_code=201)
def capture_image(request: Request, declaration_id: str) -> ImageOut:
    """camlibのRGBと取得可能な深度画像を同じ撮影として保存する。"""
    container = request.app.state.c
    container.capture.validate_capture(declaration_id)
    try:
        result = container.camera.capture()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail={"code": "camera_unavailable", "message": str(exc)}) from exc
    return ImageOut.of(container.capture.add_image(
        declaration_id, result.data, CAMERA_CONTENT_TYPE, result.meta,
        depth_data=result.depth_data, depth_content_type=result.depth_content_type,
    ))
