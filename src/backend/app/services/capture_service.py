"""セッション・宣言・撮影のユースケース。ポートにのみ依存する。"""
from __future__ import annotations
import uuid
from typing import Callable, Optional

from ..domain.errors import Conflict, InvalidInput, NotFound
from ..domain.models import Declaration, DeclarationItem, Image, Session
from ..ports import ImageStore, InstrumentCatalog, MetadataStore

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_DECLARED_TOTAL = 50


class CaptureService:
    def __init__(self, store: MetadataStore, images: ImageStore, catalog: InstrumentCatalog,
                 now: Callable[[], str], max_upload_bytes: int = 20 * 1024 * 1024):
        self._store, self._images, self._catalog = store, images, catalog
        self._now = now
        self._max_bytes = max_upload_bytes
        self._on_session_closed: list[Callable[[Session], None]] = []

    def subscribe_session_closed(self, fn: Callable[[Session], None]) -> None:
        """セッション終了イベント。レポート生成などを疎結合に接続する。"""
        self._on_session_closed.append(fn)

    # ---- sessions
    def start_session(self, **fields) -> Session:
        s = Session(session_id=uuid.uuid4().hex[:12], started_at=self._now(), **fields)
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
            except Exception:   # レポート失敗でセッション終了を妨げない
                pass
        return s

    # ---- declarations
    def create_declaration(self, session_id: str, items: list[tuple[str, int]], copy_from: Optional[str] = None) -> Declaration:
        s = self.get_session(session_id)
        if s.closed_at:
            raise Conflict("終了済みセッションには宣言できません")
        if copy_from:
            src = self.get_declaration(copy_from)
            items = [(i.instrument_uid, i.count) for i in src.items]
        if not items:
            raise InvalidInput("器具が宣言されていません")
        merged: dict[str, int] = {}
        for uid, cnt in items:
            if cnt < 1:
                raise InvalidInput(f"個数は1以上です: {uid}")
            inst = self._catalog.get(uid)
            if inst is None:
                raise InvalidInput(f"マスタに存在しない器具です: {uid}")
            if inst.status != "active":
                raise InvalidInput(f"廃止された器具は宣言できません: {uid}")
            merged[uid] = merged.get(uid, 0) + cnt
        if sum(merged.values()) > MAX_DECLARED_TOTAL:
            raise InvalidInput(f"宣言の合計個数は{MAX_DECLARED_TOTAL}以下です")
        d = Declaration(declaration_id=uuid.uuid4().hex[:12], session_id=session_id,
                        items=[DeclarationItem(u, c) for u, c in merged.items()],
                        created_at=self._now(), copied_from=copy_from)
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
    def add_image(self, declaration_id: str, data: bytes, content_type: str, meta: dict) -> Image:
        d = self.get_declaration(declaration_id)
        s = self.get_session(d.session_id)
        if s.closed_at:
            raise Conflict("終了済みセッションには撮影できません")
        if not d.confirmed:
            raise Conflict("宣言が未確認です（配置確認を完了してください）")
        if content_type not in ALLOWED_TYPES:
            raise InvalidInput(f"未対応の画像形式です: {content_type}")
        if len(data) > self._max_bytes:
            raise InvalidInput("画像サイズが大きすぎます")
        if not data:
            raise InvalidInput("画像が空です")
        image_id = uuid.uuid4().hex
        captured_at = self._now()
        key = f"{captured_at[:10]}/{s.session_id}/{image_id}"
        try:
            stored = self._images.save(key, data, content_type)    # 撮影直後に生データを確定保存
        except ValueError as e:
            raise InvalidInput(str(e))
        except Exception:
            raise InvalidInput("画像を読み取れません")
        img = Image(image_id=image_id, declaration_id=d.declaration_id, session_id=s.session_id,
                    arrangement_no=d.arrangement_no, path=stored.path, sha256=stored.sha256,
                    width=stored.width, height=stored.height, content_type=stored.content_type,
                    captured_at=captured_at, meta=meta)
        self._store.add_image(img)
        return img

    def get_image(self, image_id: str) -> Image:
        img = self._store.get_image(image_id)
        if img is None:
            raise NotFound(f"画像が見つかりません: {image_id}")
        return img

    def list_images(self, **filters) -> list[Image]:
        return self._store.list_images(**filters)

    def open_image(self, image_id: str):
        return self._images.open(self.get_image(image_id).path)
