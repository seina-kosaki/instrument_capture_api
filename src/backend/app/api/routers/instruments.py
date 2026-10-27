from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from ..schemas import InstrumentOut

router = APIRouter(prefix="/instruments", tags=["instruments"])


@router.get("", response_model=list[InstrumentOut])
def list_instruments(request: Request, q: Optional[str] = None, limit: int = Query(100, le=1000)):
    items = request.app.state.c.catalog.list(q=q)
    return [InstrumentOut.of(i) for i in items[:limit]]


@router.post("/reload")
def reload_catalog(request: Request):
    """マスタCSVを再読込（CSV更新後、APIを再起動せずに反映する）。"""
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
    return InstrumentOut.of(i)
