from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["stats"])


@router.get("/stats/daily")
def daily(request: Request, date: Optional[str] = None):
    c = request.app.state.c
    return c.stats.daily(date or c.today())


@router.get("/stats/coverage")
def coverage(request: Request):
    return request.app.state.c.stats.coverage()


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
