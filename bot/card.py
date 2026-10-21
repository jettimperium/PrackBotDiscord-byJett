"""Отрисовка карточки вызова в PNG (Pillow, без Discord-зависимостей)."""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

SCALE = 2
WIDTH = 760


def _px(value: float) -> int:
    return round(value * SCALE)


# Шрифты Windows не умеют цветные эмодзи — вырезаем их, чтобы не было «тофу».
_EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D\u20E3]")


def _clean(text: str) -> str:
    return " ".join(_EMOJI_RE.sub("", str(text)).split())


@dataclass
class CardData:
    name: str
    subtitle: str
    quote: str
    chips: list[str]
    badge: str = "КВ · DOTA 2"
    brand: str = "P2P"
    brand_note: str = "быстрое КВ"
    accent: str = "#ff4d6d"
    closed: bool = False


_FONT_CANDIDATES = {
    "bold": ("segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"),
    "regular": ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"),
}

_FONT_DIRS = (
    Path("C:/Windows/Fonts"),
    Path.home() / "AppData/Local/Microsoft/Windows/Fonts",
    Path("/usr/share/fonts/truetype/dejavu"),
    Path("/usr/share/fonts/truetype/liberation"),
    Path("/System/Library/Fonts/Supplemental"),
    Path("/Library/Fonts"),
)


@lru_cache(maxsize=64)
def _font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    for directory in _FONT_DIRS:
        for filename in _FONT_CANDIDATES[weight]:
            path = directory / filename
            if path.exists():
                return ImageFont.truetype(str(path), _px(size))
    raise RuntimeError(
        "Не найден шрифт с поддержкой кириллицы. Установи шрифт или добавь путь в _FONT_DIRS."
    )


def _rgb(value: str) -> tuple[int, int, int]:
    raw = value.strip().lstrip("#")
    if len(raw) == 3:
        raw = "".join(ch * 2 for ch in raw)
    if len(raw) != 6:
        raw = "ff4d6d"
    return tuple(int(raw[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore[return-value]


def _ellipsize(text: str, font: ImageFont.FreeTypeFont, max_width: int, measure: ImageDraw.ImageDraw) -> str:
    text = text.strip()
    if measure.textlength(text, font=font) <= max_width:
        return text
    ellipsis = "…"
    while text and measure.textlength(text + ellipsis, font=font) > max_width:
        text = text[:-1]
    return text.rstrip() + ellipsis


def _wrap(
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
    measure: ImageDraw.ImageDraw,
    max_lines: int = 3,
) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if not current or measure.textlength(candidate, font=font) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = _ellipsize(lines[-1] + "…", font, max_width, measure)
    return [_ellipsize(line, font, max_width, measure) for line in lines]


def _vertical_gradient(size: tuple[int, int], top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    width, height = size
    strip = Image.new("RGB", (1, height))
    pixels = strip.load()
    for y in range(height):
        t = y / max(1, height - 1)
        pixels[0, y] = tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
    return strip.resize((width, height))


def _circle_mask(size: int) -> Image.Image:
    big = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(big).ellipse([0, 0, size * 4 - 1, size * 4 - 1], fill=255)
    return big.resize((size, size), Image.LANCZOS)


def _avatar_layer(avatar: Image.Image | None, size: int, accent: tuple[int, int, int], letter: str) -> Image.Image:
    """Круглая аватарка с акцентным кольцом."""
    outer = size + _px(6)
    layer = Image.new("RGBA", (outer, outer), (0, 0, 0, 0))
    ImageDraw.Draw(layer).ellipse([0, 0, outer - 1, outer - 1], fill=accent + (255,))
    inset = _px(3)
    inner = size
    if avatar is not None:
        picture = avatar.convert("RGBA").resize((inner, inner), Image.LANCZOS)
        layer.paste(picture, (inset, inset), _circle_mask(inner))
    else:
        draw = ImageDraw.Draw(layer)
        draw.ellipse([inset, inset, inset + inner - 1, inset + inner - 1], fill=(34, 36, 52, 255))
        draw.text(
            (outer / 2, outer / 2),
            letter or "?",
            font=_font("bold", 30),
            fill=(235, 238, 250),
            anchor="mm",
        )
    return layer


def render_card(data: CardData, avatar: Image.Image | None = None) -> bytes:
    data = CardData(
        name=_clean(data.name),
        subtitle=_clean(data.subtitle),
        quote=_clean(data.quote),
        chips=[chip for chip in (_clean(chip) for chip in data.chips) if chip],
        badge=_clean(data.badge),
        brand=_clean(data.brand),
        brand_note=_clean(data.brand_note),
        accent=data.accent,
        closed=data.closed,
    )
    pad = 26
    avatar_size = 76
    text_x = pad + avatar_size + 16
    inner_w = WIDTH - pad * 2

    name_font = _font("bold", 24)
    sub_font = _font("regular", 14)
    badge_font = _font("bold", 12)
    quote_font = _font("bold", 20)
    chip_font = _font("regular", 14)
    brand_font = _font("bold", 14)
    note_font = _font("regular", 12)

    measure = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    accent = _rgb(data.accent)

    badge_text = _ellipsize(data.badge.strip(), badge_font, _px(180), measure)
    badge_w = int(measure.textlength(badge_text, font=badge_font)) + _px(26)
    badge_h = _px(26)

    name_max = _px(WIDTH - pad) - _px(text_x) - badge_w - _px(16)
    name = _ellipsize(data.name, name_font, name_max, measure)
    subtitle_max = _px(WIDTH - pad) - _px(text_x)
    subtitle = _ellipsize(data.subtitle, sub_font, subtitle_max, measure)

    quote_lines = _wrap(data.quote, quote_font, inner_w - _px(20), measure)
    quote_line_h = _px(27)
    quote_h = max(_px(30), len(quote_lines) * quote_line_h)

    chip_h = _px(32)
    chip_gap = _px(8)
    chip_rows: list[list[tuple[str, int]]] = []
    row: list[tuple[str, int]] = []
    row_width = 0
    for chip in data.chips:
        if not chip:
            continue
        chip_w = int(measure.textlength(chip, font=chip_font)) + _px(40)
        extra = chip_w if not row else chip_w + chip_gap
        if row and row_width + extra > _px(inner_w):
            chip_rows.append(row)
            row, row_width, extra = [], 0, chip_w
        row.append((chip, chip_w))
        row_width += extra
    if row:
        chip_rows.append(row)
    chips_h = len(chip_rows) * chip_h + max(0, len(chip_rows) - 1) * _px(9)

    quote_top = _px(pad + avatar_size + 26)
    chips_top = quote_top + quote_h + _px(18)
    footer_top = chips_top + chips_h + (_px(24) if chips_h else 0)
    height_px = footer_top + _px(22) + _px(pad)

    canvas = Image.new("RGBA", (_px(WIDTH), height_px), (0, 0, 0, 0))
    background = _vertical_gradient(canvas.size, (21, 22, 33), (10, 11, 16)).convert("RGBA")

    glow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse(
        [-_px(160), -_px(200), _px(380), _px(220)], fill=accent + (44,)
    )
    background.alpha_composite(glow.filter(ImageFilter.GaussianBlur(_px(60))))

    mask = Image.new("L", canvas.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, canvas.width - 1, canvas.height - 1], radius=_px(20), fill=255
    )
    canvas.paste(background, (0, 0), mask)
    draw = ImageDraw.Draw(canvas)

    border = _mix(accent, (72, 74, 100), 0.55)
    draw.rounded_rectangle(
        [_px(1), _px(1), canvas.width - _px(1), canvas.height - _px(1)],
        radius=_px(19),
        outline=border + (210,),
        width=_px(1),
    )

    # --- шапка -------------------------------------------------------------
    avatar_layer = _avatar_layer(avatar, _px(avatar_size), accent, data.name[:1])
    canvas.alpha_composite(avatar_layer, (_px(pad) - _px(3), _px(pad) - _px(3)))

    draw.text((_px(text_x), _px(pad + 4)), name, font=name_font, fill=(244, 245, 250))
    draw.text((_px(text_x), _px(pad + 38)), subtitle, font=sub_font, fill=(150, 154, 175))

    badge_x = canvas.width - _px(pad) - badge_w
    badge_y = _px(pad + 2)
    draw.rounded_rectangle(
        [badge_x, badge_y, badge_x + badge_w, badge_y + badge_h],
        radius=_px(8),
        fill=_mix(accent, (16, 17, 25), 0.72) + (255,),
    )
    draw.text(
        (badge_x + badge_w / 2, badge_y + badge_h / 2),
        badge_text,
        font=badge_font,
        fill=_mix(accent, (255, 255, 255), 0.55) + (255,),
        anchor="mm",
    )

    # --- цитата ------------------------------------------------------------
    quote_y = quote_top
    draw.rounded_rectangle(
        [_px(pad), quote_y + _px(2), _px(pad + 4), quote_y + quote_h - _px(4)],
        radius=_px(2),
        fill=accent + (255,),
    )
    for index, line in enumerate(quote_lines):
        draw.text(
            (_px(pad + 18), quote_y + index * quote_line_h),
            line,
            font=quote_font,
            fill=(238, 240, 248),
        )

    # --- чипы --------------------------------------------------------------
    chip_y = chips_top
    for chip_row in chip_rows:
        chip_x = _px(pad)
        for chip, chip_w in chip_row:
            draw.rounded_rectangle(
                [chip_x, chip_y, chip_x + chip_w, chip_y + chip_h],
                radius=_px(16),
                fill=(32, 34, 50, 255),
                outline=(49, 52, 74, 255),
                width=_px(1),
            )
            dot = _px(3)
            center_x = chip_x + _px(15) + dot
            center_y = chip_y + chip_h // 2
            draw.ellipse(
                [center_x - dot, center_y - dot, center_x + dot, center_y + dot],
                fill=accent + (255,),
            )
            draw.text(
                (chip_x + _px(26), center_y),
                chip,
                font=chip_font,
                fill=(214, 218, 235),
                anchor="lm",
            )
            chip_x += chip_w + chip_gap
        chip_y += chip_h + _px(9)

    # --- подвал ------------------------------------------------------------
    footer_y = footer_top
    mark = _px(22)
    draw.rounded_rectangle(
        [_px(pad), footer_y, _px(pad) + mark, footer_y + mark],
        radius=_px(6),
        fill=accent + (255,),
    )
    draw.text(
        (_px(pad) + mark / 2, footer_y + mark / 2),
        data.brand[:3].upper(),
        font=_font("bold", 10),
        fill=(18, 18, 26),
        anchor="mm",
    )
    draw.text(
        (_px(pad + 32), footer_y + mark / 2),
        data.brand,
        font=brand_font,
        fill=(222, 225, 238),
        anchor="lm",
    )
    draw.text(
        (canvas.width - _px(pad), footer_y + mark / 2),
        data.brand_note,
        font=note_font,
        fill=(118, 122, 143),
        anchor="rm",
    )

    # --- штамп «закрыт» ----------------------------------------------------
    if data.closed:
        veil = Image.new("RGBA", canvas.size, (9, 10, 16, 180))
        veil_mask = Image.new("L", canvas.size, 0)
        ImageDraw.Draw(veil_mask).rounded_rectangle(
            [0, 0, canvas.width - 1, canvas.height - 1], radius=_px(20), fill=255
        )
        canvas.alpha_composite(
            Image.composite(veil, Image.new("RGBA", canvas.size, (0, 0, 0, 0)), veil_mask)
        )
        draw = ImageDraw.Draw(canvas)
        label = "ВЫЗОВ ЗАКРЫТ"
        stamp_font = _font("bold", 18)
        label_width = int(measure.textlength(label, font=stamp_font))
        box_w, box_h = label_width + _px(36), _px(42)
        box_x, box_y = (canvas.width - box_w) // 2, (canvas.height - box_h) // 2
        draw.rounded_rectangle(
            [box_x, box_y, box_x + box_w, box_y + box_h],
            radius=_px(12),
            fill=(20, 21, 31, 235),
            outline=accent + (255,),
            width=max(1, _px(1)),
        )
        draw.text(
            (canvas.width / 2, canvas.height / 2),
            label,
            font=stamp_font,
            fill=(236, 238, 248),
            anchor="mm",
        )

    buffer = io.BytesIO()
    canvas.save(buffer, "PNG")
    return buffer.getvalue()
