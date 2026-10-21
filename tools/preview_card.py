"""Локальный предпросмотр карточки без Discord: python tools/preview_card.py"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bot.card import CardData, render_card


def sample_avatar(size: int = 256) -> Image.Image:
    top, bottom = (255, 150, 90), (150, 60, 190)
    strip = Image.new("RGB", (1, size))
    pixels = strip.load()
    for y in range(size):
        t = y / (size - 1)
        pixels[0, y] = tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
    image = strip.resize((size, size)).convert("RGBA")
    draw = ImageDraw.Draw(image)
    draw.ellipse([size * 0.22, size * 0.18, size * 0.78, size * 0.74], fill=(255, 236, 220, 255))
    draw.ellipse([size * 0.34, size * 0.38, size * 0.43, size * 0.47], fill=(40, 40, 50, 255))
    draw.ellipse([size * 0.57, size * 0.38, size * 0.66, size * 0.47], fill=(40, 40, 50, 255))
    draw.arc([size * 0.38, size * 0.48, size * 0.62, size * 0.66], 20, 160, fill=(120, 70, 60, 255), width=6)
    return image


def main() -> None:
    data = CardData(
        name="чиж",
        subtitle="@chizh · заявка на КВ",
        quote="«20:00 без смурфов»",
        chips=["Сегодня 20:00 МСК", "3 250 MMR", "Europe", "Captains Mode"],
    )
    (ROOT / "preview_open.png").write_bytes(render_card(data, sample_avatar()))
    closed = CardData(**{**data.__dict__, "closed": True})
    (ROOT / "preview_closed.png").write_bytes(render_card(closed, sample_avatar()))
    print("Готово: preview_open.png, preview_closed.png")


if __name__ == "__main__":
    main()
