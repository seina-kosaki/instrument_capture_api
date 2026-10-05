from __future__ import annotations
import hashlib
import io
from pathlib import Path
from typing import BinaryIO

from PIL import Image as PILImage

from ..ports import StoredImage

_EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


class LocalFsImageStore:
    def __init__(self, root: Path):
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def save(self, key_hint: str, data: bytes, content_type: str) -> StoredImage:
        ext = _EXT.get(content_type)
        if ext is None:
            raise ValueError(f"未対応の形式: {content_type}")
        with PILImage.open(io.BytesIO(data)) as im:   # 壊れた画像・偽装を弾く
            im.verify()
        with PILImage.open(io.BytesIO(data)) as im:
            width, height = im.size
        rel = Path(key_hint + ext)
        dest = self._root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)                         # 生データは無加工で保存
        return StoredImage(str(rel), hashlib.sha256(data).hexdigest(), width, height, content_type)

    def open(self, path: str) -> BinaryIO:
        full = (self._root / path).resolve()
        if self._root.resolve() not in full.parents:
            raise FileNotFoundError(path)
        return open(full, "rb")
