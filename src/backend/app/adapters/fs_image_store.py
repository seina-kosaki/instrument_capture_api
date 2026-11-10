from __future__ import annotations
import hashlib
import io
from pathlib import Path
from typing import BinaryIO

from PIL import Image as PILImage
import tifffile

from ..ports import DEPTH_TIFF_CONTENT_TYPE, StoredImage

_EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", DEPTH_TIFF_CONTENT_TYPE: ".tiff"}
DEPTH_DIMENSIONS = 2


class LocalFsImageStore:
    def __init__(self, root: Path):
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def save(self, key_hint: str, data: bytes, content_type: str) -> StoredImage:
        ext = _EXT.get(content_type)
        if ext is None:
            raise ValueError(f"未対応の形式: {content_type}")
        if content_type == DEPTH_TIFF_CONTENT_TYPE:
            depth_array = tifffile.imread(io.BytesIO(data))
            if depth_array.ndim != DEPTH_DIMENSIONS:
                raise ValueError("深度TIFFは2次元配列である必要があります")
            height, width = depth_array.shape
        else:
            with PILImage.open(io.BytesIO(data)) as im:   # 壊れた画像・偽装を弾く
                im.verify()
            with PILImage.open(io.BytesIO(data)) as im:
                width, height = im.size
        rel = Path(key_hint + ext)
        dest = self._root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)                         # 生データは無加工で保存
        return StoredImage(rel.as_posix(), hashlib.sha256(data).hexdigest(), width, height, content_type)

    def open(self, path: str) -> BinaryIO:
        return open(self._resolve(path), "rb")

    def delete(self, path: str) -> None:
        """ルート内の相対パスだけを削除する。"""
        target = self._resolve(path)
        if target.exists():
            target.unlink()

    def _resolve(self, path: str) -> Path:
        relative = Path(path)
        if relative.is_absolute() or not relative.parts or ".." in relative.parts:
            raise FileNotFoundError(path)
        root = self._root.resolve()
        target = root / relative
        full = target.resolve()
        if root not in full.parents or full != target:
            raise FileNotFoundError(path)
        return full
