"""ポート（抽象インターフェース）。サービス層はここにだけ依存し、具体実装を知らない。

差し替え例:
  InstrumentCatalog : CSV(モック) → 本番マスタ登録処理の出力 / DB / API
  MetadataStore     : SQLite → PostgreSQL
  ImageStore        : ローカルFS → S3 等
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import BinaryIO, Optional, Protocol

from .domain.models import Declaration, Hint, Image, Instrument, Session

DEPTH_PNG_CONTENT_TYPE = "image/png"
DEPTH_TIFF_CONTENT_TYPE = "image/tiff"


class InstrumentCatalog(Protocol):
    def list(self, q: Optional[str] = None, include_inactive: bool = False) -> list[Instrument]: ...
    def get(self, uid: str) -> Optional[Instrument]: ...


@dataclass(frozen=True)
class StoredImage:
    path: str          # ImageStore 内の相対キー
    sha256: str
    width: int
    height: int
    content_type: str


class ImageStore(Protocol):
    def save(self, key_hint: str, data: bytes, content_type: str) -> StoredImage: ...
    def open(self, path: str) -> BinaryIO: ...
    def delete(self, path: str) -> None: ...


@dataclass(frozen=True)
class CameraCapture:
    """RGBと任意の深度画像を一つの撮影結果として保存層へ渡す。

    Attributes:
        data: RGB画像のJPEGデータ。
        meta: JSON化可能な撮影メタデータ。
        depth_data: 深度値を保持するPNGまたはTIFFデータ。取得できない場合はNone。
        depth_content_type: 深度画像の保存形式。
    """

    data: bytes
    meta: dict[str, object]
    depth_data: bytes | None = None
    depth_content_type: str = DEPTH_PNG_CONTENT_TYPE


class CameraPort(Protocol):
    """camlibカメラの接続・画像取得をサービス層へ提供する。"""

    @property
    def camera_name(self) -> str: ...

    def open(self) -> None:
        """カメラを接続する。"""
        ...

    def close(self) -> None:
        """カメラを切断する。"""
        ...

    def preview(self) -> bytes:
        """最新プレビューフレームをJPEGで返す。"""
        ...

    def capture(self) -> CameraCapture:
        """RGB・任意の深度画像とメタデータを返す。"""
        ...


class MetadataStore(Protocol):
    # sessions
    def add_session(self, s: Session) -> None: ...
    def get_session(self, session_id: str) -> Optional[Session]: ...
    def update_session(self, s: Session) -> None: ...
    # declarations
    def add_declaration(self, d: Declaration) -> None: ...
    def get_declaration(self, declaration_id: str) -> Optional[Declaration]: ...
    def update_declaration(self, d: Declaration) -> None: ...
    def list_declarations(self, session_id: Optional[str] = None) -> list[Declaration]: ...
    # images
    def add_image(self, img: Image) -> None: ...
    def get_image(self, image_id: str) -> Optional[Image]: ...
    def update_image(self, img: Image) -> None: ...
    def delete_image(self, image_id: str) -> Optional[Image]: ...
    def list_images(self, *, session_id: Optional[str] = None, declaration_id: Optional[str] = None,
                    tag_status: Optional[str] = None, date: Optional[str] = None,
                    limit: int = 200, offset: int = 0) -> list[Image]: ...
    # hints
    def replace_hints(self, image_id: str, hints: list[Hint]) -> None: ...
    def list_hints(self, image_id: str) -> list[Hint]: ...
    def list_hints_for_images(self, image_ids: list[str]) -> dict[str, list[Hint]]: ...
