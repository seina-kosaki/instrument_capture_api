"""タグ付き画像（デバッグ確認用）の描画。元画像に点・端点・ラベルを重ねるだけの純粋な描画処理。

日本語フォントが見つからない環境では、ラベルを instrument_uid で描く（文字化け防止）。
"""
from __future__ import annotations
from pathlib import Path
from typing import Callable, Optional

from PIL import Image, ImageDraw, ImageFont

from ..domain.models import Hint

PALETTE = ["#e4572e", "#17a398", "#7b2cbf", "#f2a541", "#1d6fa5", "#6a994e"]
_FONTS = [
    "C:/Windows/Fonts/meiryo.ttc", "C:/Windows/Fonts/YuGothM.ttc", "C:/Windows/Fonts/msgothic.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
]


def load_font(size: int) -> tuple[ImageFont.ImageFont, bool]:
    """(フォント, 日本語が描けるか)"""
    for p in _FONTS:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size), True
            except OSError:
                continue
    try:
        return ImageFont.load_default(size=size), False
    except TypeError:
        return ImageFont.load_default(), False


def _dashed(d: ImageDraw.ImageDraw, a, b, fill, width: int, dash: int = 14, gap: int = 10) -> None:
    ax, ay = a; bx, by = b
    length = ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5
    if length == 0:
        return
    ux, uy = (bx - ax) / length, (by - ay) / length
    pos = 0.0
    while pos < length:
        end = min(pos + dash, length)
        d.line([(ax + ux * pos, ay + uy * pos), (ax + ux * end, ay + uy * end)], fill=fill, width=width)
        pos += dash + gap


def render_overlay(img: Image.Image, hints: list[Hint], color_of: Callable[[str], str],
                   names: dict[str, str], header: list[str]) -> Image.Image:
    im = img.convert("RGB")
    W, H = im.size
    d = ImageDraw.Draw(im)
    font, cjk = load_font(max(14, W // 60))
    r, lw = max(6, W // 150), max(2, W // 500)

    def P(p): return (p.x * W, p.y * H)
    def name(uid): return names.get(uid, uid) if cjk else uid

    counters: dict[str, int] = {}
    unplaced: list[str] = []
    for h in hints:
        counters[h.instrument_uid] = counters.get(h.instrument_uid, 0) + 1
        label = f"{name(h.instrument_uid)} #{counters[h.instrument_uid]}"
        if h.center is None:
            unplaced.append(f"- {h.instrument_uid} #{counters[h.instrument_uid]}: " + ("not visible" if not h.visible else "declared only (no points)"))
            continue
        col = color_of(h.instrument_uid)
        cx, cy = P(h.center)
        if h.end_a and h.end_b:
            _dashed(d, P(h.end_a), P(h.end_b), col, lw)
        for tag, pt in (("A", h.end_a), ("B", h.end_b)):
            if pt:
                x, y = P(pt)
                d.rectangle([x - r * .8, y - r * .8, x + r * .8, y + r * .8], fill=col, outline="white")
                d.text((x + r, y - r * 2), tag, fill=col, font=font)
        if h.center.status == "estimated":
            d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=col, width=lw * 2)     # 推定位置は輪郭のみ
        else:
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col, outline="white")
        l, t, rr, b = d.textbbox((0, 0), label, font=font)
        tx, ty = cx + r + 4, cy - r - (b - t) - 8
        d.rectangle([tx - 3, ty - 2, tx + (rr - l) + 3, ty + (b - t) + 4], fill=col)
        d.text((tx, ty - t), label, fill="white", font=font)

    lines = header + unplaced
    if lines:                                           # 左上に情報帯
        hf, _ = load_font(max(12, W // 80))
        h_px = [d.textbbox((0, 0), s, font=hf) for s in lines]
        bw = max(b[2] - b[0] for b in h_px) + 16
        bh = sum((b[3] - b[1]) + 6 for b in h_px) + 8
        d.rectangle([0, 0, bw, bh], fill="#0b3c49")
        y = 6
        for s, b in zip(lines, h_px):
            d.text((8, y - b[1]), s, fill="white", font=hf)
            y += (b[3] - b[1]) + 6
    return im
