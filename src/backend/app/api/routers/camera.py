"""カメラの接続状態・プレビューを公開するHTTP境界。"""
from __future__ import annotations

from collections.abc import Callable
from fastapi import APIRouter, HTTPException, Request, Response
from typing import TypeVar

router = APIRouter(prefix="/camera", tags=["camera"])
Result = TypeVar("Result")


def _run_camera_operation(operation: Callable[[], Result]) -> Result:
    """カメラ操作エラーをHTTP 503へ変換する。"""
    try:
        return operation()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail={"code": "camera_unavailable", "message": str(exc)}) from exc


@router.get("/status")
def status(request: Request) -> dict[str, str | None]:
    """カメラ接続状態を取得する。"""
    return request.app.state.c.camera.status()


@router.post("/open")
def open_camera(request: Request) -> dict[str, str | None]:
    """カメラを接続する。"""
    return _run_camera_operation(request.app.state.c.camera.open)


@router.post("/close")
def close_camera(request: Request) -> dict[str, str | None]:
    """カメラを切断する。"""
    return _run_camera_operation(request.app.state.c.camera.close)


@router.get("/preview")
def preview(request: Request) -> Response:
    """最新のプレビューフレームをJPEGで返す。"""
    data = _run_camera_operation(request.app.state.c.camera.preview)
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})