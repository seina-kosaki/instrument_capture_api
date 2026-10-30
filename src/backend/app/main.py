"""コンポジションルート。具体実装の選択と配線はここだけで行う。"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .adapters.camlib_camera import CamlibCamera
from .adapters.fs_image_store import LocalFsImageStore
from .adapters.legacy_storage_migration import migrate_legacy_storage, relocate_legacy_data_root
from .adapters.session_bundle_store import SessionBundleMetadataStore
from .adapters.sqlite_catalog import SqliteInstrumentCatalog
from .api.container import Container
from .api.routers import camera, declarations, images, instruments, sessions, stats
from .config import Settings
from .domain.errors import Conflict, DomainError, InvalidInput, NotFound, TagValidationFailed
from .ports import CameraPort, ImageStore, InstrumentCatalog, MetadataStore
from .services.camera_service import CameraService
from .services.capture_service import CaptureService
from .services.debug_render_service import TaggedImageRenderer
from .services.export_service import ExportService
from .services.report_service import ReportService
from .services.stats_service import StatsService
from .services.tagging_service import TaggingService

_STATUS = {NotFound: 404, Conflict: 409, InvalidInput: 400, TagValidationFailed: 422}


def create_app(
    settings: Settings | None = None, *, catalog: InstrumentCatalog | None = None, store: MetadataStore | None = None, image_store: ImageStore | None = None, camera_port: CameraPort | None = None, clock: Callable[[], datetime] | None = None
) -> FastAPI:
    s = settings or Settings.from_env()
    if s.legacy_data_dir is not None:
        relocate_legacy_data_root(s.legacy_data_dir, s.data_dir)
    tz = ZoneInfo(s.timezone)
    clock = clock or (lambda: datetime.now(tz))
    now = lambda: clock().isoformat(timespec="seconds")  # noqa: E731
    today = lambda: clock().date().isoformat()  # noqa: E731

    catalog = catalog or SqliteInstrumentCatalog(s.catalog_db)
    if store is None:
        migrate_legacy_storage(s.data_dir, catalog)
        store = SessionBundleMetadataStore(s.data_dir)
    image_store = image_store or LocalFsImageStore(s.data_dir)
    camera_adapter = camera_port or CamlibCamera(
        s.camera_param_yaml or (Path(__file__).resolve().parents[2] / "config" / "hardware_mecheye" / "camera_param.yaml"),
        s.camera_id_yaml or (Path(__file__).resolve().parents[2] / "config" / "hardware_mecheye" / "camera_id.yaml"),
        s.camera_name,
        s.camera_buffer_name,
    )
    camera_service = CameraService(camera_adapter)

    capture = CaptureService(store, image_store, catalog, now, s.max_upload_mb * 1024 * 1024)
    tagging = TaggingService(store, catalog, now)
    stats_svc = StatsService(store, catalog, s.target_single_arrangements, s.target_multi_arrangements)
    reports = ReportService(stats_svc, s.data_dir / "reports")
    # タグ付き画像（デバッグ確認用）: 学習用の images/ とは別の debug_tagged/ に保存する
    debug = TaggedImageRenderer(store, image_store, catalog, image_store if s.save_debug_images else None)
    if s.save_debug_images:
        tagging.subscribe_tags_saved(debug.save)
    # セッション終了 → 日次サマリー出力（イベント購読で疎結合に接続）
    capture.subscribe_session_closed(lambda sess: reports.write_daily(sess.closed_at[:10] if sess.closed_at else today()))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        try:
            camera_service.close()
        except RuntimeError:
            pass
        try:  # API終了時にも当日分を出力
            reports.write_daily(today())
        except Exception:
            pass

    app = FastAPI(title="Instrument Capture API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=list(s.cors_origins), allow_methods=["*"], allow_headers=["*"])
    app.state.c = Container(catalog=catalog, capture=capture, tagging=tagging, stats=stats_svc, reports=reports, export=ExportService(store, catalog), debug=debug, camera=camera_service, today=today)

    @app.exception_handler(DomainError)
    async def _domain_error(_: Request, exc: DomainError):
        status = next((v for k, v in _STATUS.items() if isinstance(exc, k)), 400)
        return JSONResponse(status_code=status, content={"code": exc.code, "message": exc.message, "details": exc.details})

    @app.get("/health", tags=["meta"])
    def health():
        return {"status": "ok", "instruments": len(catalog.list())}

    for r in (camera.router, instruments.router, sessions.router, declarations.router, images.router, stats.router):
        app.include_router(r)
    return app
