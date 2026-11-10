"""セッション・宣言・撮影のユースケース。ポートにのみ依存する。"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import PurePosixPath
from typing import Optional

from ..domain.errors import Conflict, InvalidInput, NotFound
from ..domain.models import Declaration, DeclarationItem, Image, Session
from ..ports import DEPTH_PNG_CONTENT_TYPE, ImageStore, InstrumentCatalog, MetadataStore

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_DECLARED_INSTRUMENT_TYPES = 50
DEPTH_DIRECTORY = "depth"


class CaptureService:
    def __init__(self, store: MetadataStore, images: ImageStore, catalog: InstrumentCatalog, now: Callable[[], str], max_upload_bytes: int = 20 * 1024 * 1024):
        self._store, self._images, self._catalog = store, images, catalog
        self._now = now
        self._max_bytes = max_upload_bytes
        self._on_session_closed: list[Callable[[Session], None]] = []

    def subscribe_session_closed(self, fn: Callable[[Session], None]) -> None:
        """セッション終了イベント。レポート生成などを疎結合に接続する。"""
        self._on_session_closed.append(fn)

    # ---- sessions
    def start_session(self, **fields) -> Session:
        started_at = self._now()
        sortable_time = datetime.fromisoformat(started_at).strftime("%H%M%S_%f")
        session_id = f"session_{sortable_time}_{uuid.uuid4().hex[:6]}"
        s = Session(session_id=session_id, started_at=started_at, **fields)
        self._store.add_session(s)
        return s

    def get_session(self, session_id: str) -> Session:
        s = self._store.get_session(session_id)
        if s is None:
            raise NotFound(f"セッションが見つかりません: {session_id}")
        return s

    def close_session(self, session_id: str) -> Session:
        s = self.get_session(session_id)
        if s.closed_at is None:
            s.closed_at = self._now()
            self._store.update_session(s)
        for fn in self._on_session_closed:
            try:
                fn(s)
            except Exception:  # レポート失敗でセッション終了を妨げない
                pass
        return s

    def delete_session(self, session_id: str) -> Session:
        """終了済みセッションのバンドルを削除する。

        Args:
            session_id: 削除対象セッションのID。

        Returns:
            削除前のセッション情報。

        Raises:
            Conflict: セッションが未終了、またはストアが削除に対応しない場合。
            NotFound: セッションが存在しない場合。
        """
        session = self.get_session(session_id)
        if session.closed_at is None:
            raise Conflict("撮影中のセッションは削除できません。先に終了してください")
        delete_bundle = getattr(self._store, "delete_session", None)
        if delete_bundle is None:
            raise Conflict("この保存先はセッション削除に対応していません")
        if not delete_bundle(session_id):
            raise NotFound(f"セッションが見つかりません: {session_id}")
        return session

    # ---- declarations
    def create_declaration(self, session_id: str, instrument_uids: list[str], copy_from: str | None = None) -> Declaration:
        s = self.get_session(session_id)
        if s.closed_at:
            raise Conflict("終了済みセッションには宣言できません")
        if copy_from:
            src = self.get_declaration(copy_from)
            instrument_uids = [item.instrument_uid for item in src.items]
            name_snapshots = {item.instrument_uid: item.instrument_name for item in src.items}
        else:
            name_snapshots = {}
        if not instrument_uids:
            raise InvalidInput("器具が宣言されていません")
        names: dict[str, str] = {}
        for uid in instrument_uids:
            if uid in names:
                continue
            inst = self._catalog.get(uid)
            if inst is None:
                raise InvalidInput(f"マスタに存在しない器具です: {uid}")
            if inst.status != "active":
                raise InvalidInput(f"廃止された器具は宣言できません: {uid}")
            names[uid] = name_snapshots.get(uid) or inst.name
        if len(names) > MAX_DECLARED_INSTRUMENT_TYPES:
            raise InvalidInput(f"宣言できる器具の種類は{MAX_DECLARED_INSTRUMENT_TYPES}以下です")
        d = Declaration(declaration_id=uuid.uuid4().hex[:12], session_id=session_id, items=[DeclarationItem(uid, names[uid]) for uid in names], created_at=self._now(), copied_from=copy_from)
        self._store.add_declaration(d)
        return d

    def get_declaration(self, declaration_id: str) -> Declaration:
        d = self._store.get_declaration(declaration_id)
        if d is None:
            raise NotFound(f"宣言が見つかりません: {declaration_id}")
        return d

    def list_declarations(self, session_id: str) -> list[Declaration]:
        self.get_session(session_id)
        return self._store.list_declarations(session_id)

    def confirm_declaration(self, declaration_id: str) -> Declaration:
        d = self.get_declaration(declaration_id)
        if not d.confirmed:
            d.confirmed, d.confirmed_at = True, self._now()
            self._store.update_declaration(d)
        return d

    def rearrange(self, declaration_id: str) -> Declaration:
        """器具を置き直した（配置番号を進める）。連写と置き直しを区別するため。"""
        d = self.get_declaration(declaration_id)
        if not d.confirmed:
            raise Conflict("宣言が未確認です")
        d.arrangement_no += 1
        self._store.update_declaration(d)
        return d

    # ---- images
    def add_image(self, declaration_id: str, data: bytes, content_type: str, meta: dict[str, object], depth_data: bytes | None = None, depth_content_type: str = DEPTH_PNG_CONTENT_TYPE) -> Image:
        """RGBと任意の深度画像を保存し、一つの撮影レコードへ登録する。

        Args:
            declaration_id: 撮影対象の確認済み宣言ID。
            data: RGB画像データ。
            content_type: RGB画像のメディアタイプ。
            meta: 撮影メタデータ。
            depth_data: 深度値を保持する画像データ。未取得時はNone。
            depth_content_type: 深度画像の保存形式。

        Returns:
            保存した画像パスを含む撮影レコード。

        Raises:
            InvalidInput: 画像が空、上限超過、または読み取り不能の場合。
            Conflict: 宣言未確認、またはセッション終了済みの場合。
            NotFound: 宣言またはセッションが存在しない場合。
        """
        d = self.validate_capture(declaration_id)
        s = self.get_session(d.session_id)
        if content_type not in ALLOWED_TYPES:
            raise InvalidInput(f"未対応の画像形式です: {content_type}")
        if len(data) > self._max_bytes:
            raise InvalidInput("画像サイズが大きすぎます")
        if not data:
            raise InvalidInput("画像が空です")
        if depth_data is not None and (not depth_data or len(depth_data) > self._max_bytes):
            raise InvalidInput("深度画像が空、またはサイズが大きすぎます")
        image_id = uuid.uuid4().hex
        captured_at = self._now()
        session_date = s.started_at[:10]
        key = f"{session_date}/{s.session_id}/raw/{image_id}"
        saved_paths: list[str] = []
        depth_path: str | None = None
        try:
            stored = self._images.save(key, data, content_type)  # 撮影直後に生データを確定保存
            saved_paths.append(stored.path)
            if depth_data is not None:
                depth_key = f"{session_date}/{s.session_id}/{DEPTH_DIRECTORY}/{image_id}"
                depth_stored = self._images.save(depth_key, depth_data, depth_content_type)
                depth_path = depth_stored.path
                saved_paths.append(depth_path)
        except ValueError as e:
            for path in saved_paths:
                self._images.delete(path)
            raise InvalidInput(str(e)) from e
        except Exception as exc:
            for path in saved_paths:
                self._images.delete(path)
            raise InvalidInput("画像を読み取れません") from exc
        camera_name = str(meta.get("camera_name") or "unknown")
        camera_status = str(meta.get("camera_status") or ("unknown" if camera_name == "unknown" else "ready"))
        versioned_meta = {"schema_version": 1, **meta}
        img = Image(
            image_id=image_id,
            declaration_id=d.declaration_id,
            session_id=s.session_id,
            arrangement_no=d.arrangement_no,
            path=stored.path,
            sha256=stored.sha256,
            width=stored.width,
            height=stored.height,
            content_type=stored.content_type,
            captured_at=captured_at,
            meta=versioned_meta,
            camera_name=camera_name,
            camera_status=camera_status,
            location=s.location,
            depth_path=depth_path,
        )
        try:
            self._store.add_image(img)
        except Exception:
            for path in saved_paths:
                self._images.delete(path)
            raise
        return img

    def delete_image(self, image_id: str) -> Image:
        """画像とタグを削除し、対応するRGB・深度・デバッグ画像も削除する。"""
        image = self.get_image(image_id)
        if not image_id or image_id in {".", ".."} or PurePosixPath(image_id).name != image_id or "\\" in image_id or ":" in image_id:
            raise ValueError("画像IDが不正です")
        parts = PurePosixPath(image.path)
        if (
            "\\" in image.path
            or ":" in image.path
            or len(parts.parts) != 4
            or parts.parts[2] != "raw"
            or parts.parts[1] != image.session_id
            or parts.as_posix() != image.path
            or PurePosixPath(parts.parts[0]).name != parts.parts[0]
            or PurePosixPath(parts.parts[3]).stem != image_id
            or PurePosixPath(parts.parts[3]).suffix not in {".jpg", ".png", ".webp"}
        ):
            raise ValueError("画像の保存パスが不正です")
        try:
            if datetime.fromisoformat(parts.parts[0]).date().isoformat() != parts.parts[0]:
                raise ValueError("画像の保存日付が不正です")
        except ValueError as exc:
            raise ValueError("画像の保存日付が不正です") from exc

        bundle_path = "/".join(parts.parts[:2])
        depth_path = image.depth_path
        if depth_path is not None:
            depth_parts = PurePosixPath(depth_path)
            if (
                "\\" in depth_path
                or ":" in depth_path
                or len(depth_parts.parts) != 4
                or depth_parts.parts[:2] != parts.parts[:2]
                or depth_parts.parts[2] != "depth"
                or PurePosixPath(depth_parts.parts[3]).stem != image_id
                or depth_parts.parts[3].rsplit(".", 1)[-1] not in {"png", "tiff"}
                or depth_parts.as_posix() != depth_path
            ):
                raise ValueError("深度画像の保存パスが不正です")

        self._images.delete(image.path)
        if depth_path is not None:
            self._images.delete(depth_path)
        self._images.delete(f"{bundle_path}/debug/{image_id}.jpg")
        removed = self._store.delete_image(image_id)
        if removed is None:
            raise NotFound(f"画像が見つかりません: {image_id}")
        return image

    def validate_capture(self, declaration_id: str) -> Declaration:
        """撮影前に宣言とセッションの状態を検証する。

        カメラAPIが無効な撮影操作でハードウェアを駆動しないよう、画像取得前にも呼び出す。

        Args:
            declaration_id: 撮影対象の宣言ID。

        Returns:
            撮影可能な宣言。

        Raises:
            Conflict: セッション終了済み、または宣言未確認の場合。
            NotFound: 宣言またはセッションが存在しない場合。
        """
        d = self.get_declaration(declaration_id)
        s = self.get_session(d.session_id)
        if s.closed_at:
            raise Conflict("終了済みセッションには撮影できません")
        if not d.confirmed:
            raise Conflict("宣言が未確認です（配置確認を完了してください）")
        return d

    def get_image(self, image_id: str) -> Image:
        img = self._store.get_image(image_id)
        if img is None:
            raise NotFound(f"画像が見つかりません: {image_id}")
        return img

    def list_images(self, **filters) -> list[Image]:
        return self._store.list_images(**filters)

    def open_image(self, image_id: str):
        return self._images.open(self.get_image(image_id).path)
