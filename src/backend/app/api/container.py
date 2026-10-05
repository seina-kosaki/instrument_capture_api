from __future__ import annotations
from dataclasses import dataclass

from ..ports import InstrumentCatalog
from ..services.capture_service import CaptureService
from ..services.report_service import ReportService
from ..services.stats_service import StatsService
from ..services.tagging_service import TaggingService


@dataclass
class Container:
    """ルーターが使うサービスの束。ルーターは具体実装（SQLite等）を知らない。"""
    catalog: InstrumentCatalog
    capture: CaptureService
    tagging: TaggingService
    stats: StatsService
    reports: ReportService
    today: callable   # () -> "YYYY-MM-DD"
