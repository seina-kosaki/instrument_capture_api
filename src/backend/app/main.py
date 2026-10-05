"""コンポジションルート。具体実装の選択と配線はここだけで行う。"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .adapters.csv_catalog import CsvInstrumentCatalog
from .adapters.fs_image_store import LocalFsImageStore
from .adapters.sqlite_store import SqliteMetadataStore
from .api.container import Container
from .api.routers import declarations, images, instruments, sessions, stats
from .config import Settings
from .domain.errors import Conflict, DomainError, InvalidInput, NotFound, TagValidationFailed
from .ports import ImageStore, InstrumentCatalog, MetadataStore
from .services.capture_service import CaptureService
from .services.report_service import ReportService
from .services.stats_service import StatsService
from .services.tagging_service import TaggingService

_STATUS = {NotFound: 404, Conflict: 409, InvalidInput: 400, TagValidationFailed: 422}


def create_app(settings: Settings | None = None, *, catalog: InstrumentCatalog | None = None, store: MetadataStore | None = None, image_store: ImageStore | None = None, clock: Callable[[], datetime] | None = None) -> FastAPI:
    s = settings or Settings.from_env()
    tz = ZoneInfo(s.timezone)
    clock = clock or (lambda: datetime.now(tz))
    now = lambda: clock().isoformat(timespec="seconds")  # noqa: E731
    today = lambda: clock().date().isoformat()  # noqa: E731

    catalog = catalog or CsvInstrumentCatalog(s.catalog_csv)
    store = store or SqliteMetadataStore(s.data_dir / "meta.sqlite3")
    image_store = image_store or LocalFsImageStore(s.data_dir / "images")

    capture = CaptureService(store, image_store, catalog, now, s.max_upload_mb * 1024 * 1024)
    tagging = TaggingService(store, catalog, now)
    stats_svc = StatsService(store, catalog, s.target_single_arrangements, s.target_multi_arrangements)
    reports = ReportService(stats_svc, s.data_dir / "reports")
    # セッション終了 → 日次サマリー出力（イベント購読で疎結合に接続）
    capture.subscribe_session_closed(lambda sess: reports.write_daily(sess.closed_at[:10] if sess.closed_at else today()))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        try:  # API終了時にも当日分を出力
            reports.write_daily(today())
        except Exception:
            pass

    app = FastAPI(title="Instrument Capture API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=list(s.cors_origins), allow_methods=["*"], allow_headers=["*"])
    app.state.c = Container(catalog=catalog, capture=capture, tagging=tagging, stats=stats_svc, reports=reports, today=today)

    @app.exception_handler(DomainError)
    async def _domain_error(_: Request, exc: DomainError):
        status = next((v for k, v in _STATUS.items() if isinstance(exc, k)), 400)
        return JSONResponse(status_code=status, content={"code": exc.code, "message": exc.message, "details": exc.details})

    @app.get("/health", tags=["meta"])
    def health():
        return {"status": "ok", "instruments": len(catalog.list())}

    for r in (instruments.router, sessions.router, declarations.router, images.router, stats.router):
        app.include_router(r)
    return app
