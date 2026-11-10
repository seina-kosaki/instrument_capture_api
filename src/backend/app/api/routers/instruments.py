"""器具カタログの検索とサンプル画像配信API。"""

from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse

from ...domain.models import Instrument
from ..schemas import InstrumentOut

router = APIRouter(prefix="/instruments", tags=["instruments"])


def _sample_image_path(request: Request, uid: str) -> Path | None:
    path_resolver = getattr(request.app.state.c.catalog, "sample_image_path", None)
    return path_resolver(uid) if callable(path_resolver) else None


def _instrument_out(request: Request, instrument: Instrument) -> InstrumentOut:
    return InstrumentOut.of(instrument, sample_image_available=_sample_image_path(request, instrument.instrument_uid) is not None)


@router.get("", response_model=list[InstrumentOut])
def list_instruments(request: Request, q: str | None = None, limit: int = Query(100, le=1000)):
    items = request.app.state.c.catalog.list(q=q)
    return [_instrument_out(request, i) for i in items[:limit]]


@router.get("/{uid}/sample-image")
def get_sample_image(request: Request, uid: str) -> FileResponse:
    """登録されたサンプル画像を配信する。"""
    image_path = _sample_image_path(request, uid)
    if image_path is None:
        raise HTTPException(404, "sample image not found")
    media_type, _ = mimetypes.guess_type(image_path.name)
    return FileResponse(image_path, media_type=media_type or "application/octet-stream")


@router.post("/reload")
def reload_catalog(request: Request):
    """器具マスタSQLiteを再読込し、DB更新をAPI再起動なしで反映する。"""
    cat = request.app.state.c.catalog
    reload = getattr(cat, "reload", None)
    if reload is None:
        raise HTTPException(501, "このカタログは再読込に対応していません")
    try:
        reload()
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"count": len(cat.list(include_inactive=True))}


@router.get("/{uid}", response_model=InstrumentOut)
def get_instrument(request: Request, uid: str):
    i = request.app.state.c.catalog.get(uid)
    if i is None:
        raise HTTPException(404, "not found")
    return _instrument_out(request, i)
