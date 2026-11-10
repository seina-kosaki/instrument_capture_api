from __future__ import annotations

from typing import Any, Optional
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["stats"])


def _include_instrument_details(request: Request, result: dict[str, Any]) -> dict[str, Any]:
    """Attach catalog details and an available sample-image URL to each stats row."""
    catalog = request.app.state.c.catalog
    sample_image_path = getattr(catalog, "sample_image_path", None)
    for row in result["instruments"]:
        uid = row["instrument_uid"]
        instrument = catalog.get(uid)
        row["name_ja"] = instrument.name_ja if instrument is not None else ""
        row["model_number"] = instrument.model_number if instrument is not None else None
        image_available = callable(sample_image_path) and sample_image_path(uid) is not None
        row["sample_image_url"] = f"/instruments/{quote(uid, safe='')}/sample-image" if image_available else None
    return result


@router.get("/stats/daily")
def daily(request: Request, date: Optional[str] = None):
    c = request.app.state.c
    return _include_instrument_details(request, c.stats.daily(date or c.today()))


@router.get("/stats/coverage")
def coverage(request: Request):
    result = request.app.state.c.stats.coverage()
    return _include_instrument_details(request, result)


@router.get("/export/hints")
def export_hints(request: Request, date: Optional[str] = None):
    """解析用: 1ヒント=1行のフラットな表（JSON）。クライアント側でCSV化する。"""
    return request.app.state.c.export.hint_rows(date)


@router.post("/reports/daily")
def write_report(request: Request, date: Optional[str] = None):
    c = request.app.state.c
    return c.reports.write_daily(date or c.today())


@router.get("/reports/daily", response_class=HTMLResponse)
def report_html(request: Request, date: Optional[str] = None):
    c = request.app.state.c
    return HTMLResponse(c.reports.render_html(c.reports.build(date or c.today())))
