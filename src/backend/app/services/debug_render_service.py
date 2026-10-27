"""タグ付き画像（デバッグ確認用）の生成と保存。

保存先は学習用の画像（images/）とは別の領域（debug_tagged/）。学習パイプラインには絶対に流さない。
正本は「生画像 + タグ」であり、この画像はいつでも再生成できる生成物。
"""
from __future__ import annotations
import io
from pathlib import PurePosixPath
from typing import Optional

from PIL import Image

from ..adapters.overlay_renderer import PALETTE, render_overlay
from ..domain.errors import NotFound
from ..ports import ImageStore, InstrumentCatalog, MetadataStore


class TaggedImageRenderer:
    def __init__(self, store: MetadataStore, images: ImageStore, catalog: InstrumentCatalog,
                 debug_images: Optional[ImageStore] = None):
        self._store, self._images, self._catalog, self._debug = store, images, catalog, debug_images

    def render_jpeg(self, image_id: str) -> bytes:
        img = self._store.get_image(image_id)
        if img is None:
            raise NotFound(f"画像が見つかりません: {image_id}")
        hints = self._store.list_hints(image_id)
        insts = self._catalog.list(include_inactive=True)
        order = sorted(i.instrument_uid for i in insts)
        names = {i.instrument_uid: i.name for i in insts}
        color_of = lambda uid: PALETTE[order.index(uid) % len(PALETTE)] if uid in order else "#444444"   # noqa: E731
        header = [f"img {image_id[:8]}  arr={img.arrangement_no}  declared_types={len(decl.items) if (decl := self._store.get_declaration(img.declaration_id)) else '?'}  rev={img.tag_revision}  tagged_by={img.tagged_by or '-'}"]
        with self._images.open(img.path) as f:
            src = Image.open(io.BytesIO(f.read()))
            src.load()
        out = io.BytesIO()
        render_overlay(src, hints, color_of, names, header).save(out, "JPEG", quality=90)
        return out.getvalue()

    def save(self, image_id: str) -> Optional[str]:
        """デバッグ画像を保存（再タグ付けのたびに上書き）。保存先が未設定なら何もしない。"""
        if self._debug is None:
            return None
        img = self._store.get_image(image_id)
        bundle_path = PurePosixPath(img.path).parent.parent
        key = (bundle_path / "debug" / img.image_id).as_posix()
        return self._debug.save(key, self.render_jpeg(image_id), "image/jpeg").path
