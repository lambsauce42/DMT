from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont
import math
import numpy as np
import os


def _resolve_font_path(candidates: list[str]) -> Optional[str]:
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return None


_WIN_FONT_DIR = os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts")
_WSL_FONT_DIR = "/mnt/c/Windows/Fonts"

FONT_REG = _resolve_font_path(
    [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        os.path.join(_WIN_FONT_DIR, "segoeui.ttf"),
        os.path.join(_WIN_FONT_DIR, "arial.ttf"),
        os.path.join(_WSL_FONT_DIR, "segoeui.ttf"),
        os.path.join(_WSL_FONT_DIR, "arial.ttf"),
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Helvetica.ttf",
    ]
)
FONT_BOLD = _resolve_font_path(
    [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        os.path.join(_WIN_FONT_DIR, "segoeuib.ttf"),
        os.path.join(_WIN_FONT_DIR, "arialbd.ttf"),
        os.path.join(_WSL_FONT_DIR, "segoeuib.ttf"),
        os.path.join(_WSL_FONT_DIR, "arialbd.ttf"),
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Helvetica Bold.ttf",
    ]
)
FONT_OBLIQUE = _resolve_font_path(
    [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Oblique.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Italic.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansOblique.ttf",
        os.path.join(_WIN_FONT_DIR, "segoeuii.ttf"),
        os.path.join(_WIN_FONT_DIR, "ariali.ttf"),
        os.path.join(_WSL_FONT_DIR, "segoeuii.ttf"),
        os.path.join(_WSL_FONT_DIR, "ariali.ttf"),
        "/System/Library/Fonts/Supplemental/Arial Italic.ttf",
        "/System/Library/Fonts/Supplemental/Helvetica Oblique.ttf",
    ]
)


def _load_font(path: Optional[str], size: int):
    if path:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()


RARITY_COLORS: Dict[str, tuple[int, int, int]] = {
    "common": (255, 255, 255),
    "uncommon": (70, 210, 120),
    "rare": (80, 140, 255),
    "epic": (170, 90, 255),
    "legendary": (255, 165, 60),
    "artifact": (70, 235, 220),
}

_ITEM_ICON_DIRS = [
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets", "itemicons")),
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets", "iconitems")),
]
_ICON_BG_CACHE: Dict[tuple[tuple[int, int, int], int, float], Image.Image] = {}


def _icon_gradient_bg(
    size: int, rarity_rgb: tuple[int, int, int], curve: float
) -> Image.Image:
    curve = max(0.1, float(curve))
    cache_key = (rarity_rgb, size, round(curve, 2))
    cached = _ICON_BG_CACHE.get(cache_key)
    if cached is not None:
        return cached.copy()

    W = H = size
    y = np.linspace(-1.0, 1.0, H, dtype=np.float32)[:, None]
    x = np.linspace(-1.0, 1.0, W, dtype=np.float32)[None, :]
    p = 4.0
    dist = (np.abs(x) ** p + np.abs(y) ** p) ** (1.0 / p)
    dist = np.clip(dist, 0.0, 1.0)

    center = np.array(_mix(rarity_rgb, (255, 255, 255), 0.30), dtype=np.float32)
    edge = np.array(_mix(rarity_rgb, (0, 0, 0), 0.55), dtype=np.float32)

    t = dist
    t = t * t * (3.0 - 2.0 * t)  # smoothstep to flatten center/edge
    t = t ** curve
    col = center * (1.0 - t[..., None]) + edge * t[..., None]
    col = np.clip(col, 0, 255).astype(np.uint8)
    alpha = np.full((H, W, 1), 255, dtype=np.uint8)
    rgba = np.concatenate([col, alpha], axis=2)
    img = Image.fromarray(rgba, mode="RGBA")
    _ICON_BG_CACHE[cache_key] = img
    return img.copy()


def _resolve_icon_path(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    if os.path.exists(path):
        return path
    base = os.path.basename(path)
    for icon_dir in _ITEM_ICON_DIRS:
        candidate = os.path.join(icon_dir, base)
        if os.path.exists(candidate):
            return candidate
    return None


@dataclass
class ItemCardSpec:
    title: str
    rarity: str = "uncommon"
    classes: List[str] = field(default_factory=list)  # Empty list means "All Classes"
    stats: List[Tuple[str, str]] = field(default_factory=list)
    effects: List[str] = field(default_factory=list)
    flavor_text: str = ""
    icon_path: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    level: int = 1
    fused_stats_effects: bool = False
    show_level: bool = True
    show_rarity: bool = True
    show_icon_padding: bool = True


@dataclass
class RenderOptions:
    width: int = 350  # 30% narrower than the previous 500px card
    height: Optional[int] = None
    margin: int = 12
    scale: float = 3.0
    title_scale: float = 1.0
    body_scale: float = 1.0
    label_scale: float = 0.85

    base_bg: tuple[int, int, int] = (12, 12, 16)
    outside_bg: tuple[int, int, int] = (0, 0, 0)
    outside_alpha: int = 255
    panel_color: tuple[int, int, int] = (28, 28, 36)
    border_color: tuple[int, int, int] = (92, 92, 110)
    border_soft: tuple[int, int, int] = (60, 60, 74)
    text_color: tuple[int, int, int] = (238, 238, 244)

    panel_inner_glow: bool = True
    outer_rarity_glow: bool = True

    content_inset: int = 16
    content_bottom_inset: int = 28  # Space for bottom ornament
    header_padding: int = 14

    icon_fit_mode: str = "cover"
    icon_image_scale: float = 0.9
    icon_bg_curve: float = 1.8
    icon_inner_pad: int = 0
    icon_trim_black: bool = True
    icon_frame_width: int = 3


@dataclass
class RenderedCard:
    image: Image.Image
    hitboxes: Dict[str, Tuple[int, int, int, int]]


def _mix(a, b, t: float):
    return (
        int(a[0] + (b[0] - a[0]) * t),
        int(a[1] + (b[1] - a[1]) * t),
        int(a[2] + (b[2] - a[2]) * t),
    )


def _text_size(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int]:
    bb = draw.textbbox((0, 0), text, font=font)
    return (bb[2] - bb[0], bb[3] - bb[1])


def _text_metrics(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int, int]:
    """Return (width, height, y_offset) where y_offset is how far below y=0 the text starts."""
    bb = draw.textbbox((0, 0), text, font=font)
    return (bb[2] - bb[0], bb[3] - bb[1], bb[1])


def _px(value: float, minimum: int = 0) -> int:
    rounded = int(round(value))
    return rounded if rounded >= minimum else minimum


def _rarity_gradient(W: int, H: int, base_bg, rarity_rgb):
    c0 = np.array(_mix(base_bg, rarity_rgb, 0.24), dtype=np.float32)
    c1 = np.array(_mix(base_bg, rarity_rgb, 0.64), dtype=np.float32)

    xs = np.linspace(0.0, 1.0, W, dtype=np.float32)[None, :]
    ys = np.linspace(0.0, 1.0, H, dtype=np.float32)[:, None]
    t = (xs + ys) / 2.0
    v = (1.0 - ys) * 0.08
    col = c0 + (c1 - c0) * t[..., None] + (255.0 * v[..., None] * 0.02)

    col = np.clip(col, 0, 255).astype(np.uint8)
    alpha = np.full((H, W, 1), 255, dtype=np.uint8)
    rgba = np.concatenate([col, alpha], axis=2)
    return Image.fromarray(rgba, mode="RGBA")


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: int):
    words = text.split()
    lines, cur = [], []
    for w in words:
        if _text_size(draw, w, font)[0] > max_width:
            parts = _split_long_word(draw, w, font, max_width)
            if cur:
                lines.append(" ".join(cur))
                cur = []
            for part in parts[:-1]:
                lines.append(part)
            if parts:
                cur = [parts[-1]]
            continue
        cand = (" ".join(cur + [w])).strip()
        if not cand:
            continue
        if _text_size(draw, cand, font)[0] <= max_width:
            cur.append(w)
        else:
            if cur:
                lines.append(" ".join(cur))
            cur = [w]
    if cur:
        lines.append(" ".join(cur))
    return lines


def fit_title(
    draw: ImageDraw.ImageDraw,
    title: str,
    max_width: int,
    max_lines: int,
    start_size: int,
    min_size: int,
    max_height: Optional[int] = None,
    line_gap: int = 0,
):
    size = start_size
    while size >= min_size:
        font = _load_font(FONT_BOLD, size)
        words = title.split()
        lines, cur = [], []
        for w in words:
            if _text_size(draw, w, font)[0] > max_width:
                parts = _split_long_word(draw, w, font, max_width)
                if cur:
                    lines.append(" ".join(cur))
                    cur = []
                for part in parts[:-1]:
                    lines.append(part)
                if parts:
                    cur = [parts[-1]]
                continue
            cand = (" ".join(cur + [w])).strip()
            if _text_size(draw, cand, font)[0] <= max_width:
                cur.append(w)
            else:
                if cur:
                    lines.append(" ".join(cur))
                cur = [w]
        if cur:
            lines.append(" ".join(cur))
        if lines and len(lines) <= max_lines and max(
            _text_size(draw, ln, font)[0] for ln in lines
        ) <= max_width:
            if max_height is not None:
                _, h = _text_size(draw, "Ag", font)
                line_h = h + line_gap
                if line_h * len(lines) > max_height:
                    size -= 1
                    continue
            return font, lines
        size -= 1
    font = _load_font(FONT_BOLD, min_size)
    words = title.split()
    lines: list[str] = []
    cur: list[str] = []
    overflowed = False
    for w in words:
        if _text_size(draw, w, font)[0] > max_width:
            parts = _split_long_word(draw, w, font, max_width)
            if cur:
                lines.append(" ".join(cur))
                cur = []
            for part in parts:
                if len(lines) >= max_lines:
                    overflowed = True
                    break
                lines.append(part)
            if overflowed:
                break
            continue
        cand = (" ".join(cur + [w])).strip()
        if _text_size(draw, cand, font)[0] <= max_width:
            cur.append(w)
            continue
        if cur:
            lines.append(" ".join(cur))
            cur = []
        if len(lines) >= max_lines:
            overflowed = True
            break
        cur = [w]
    if cur and not overflowed and len(lines) < max_lines:
        lines.append(" ".join(cur))
    if not lines:
        return font, ["..."]
    if overflowed or len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and _text_size(draw, last + "...", font)[0] > max_width:
            last = last[:-1]
        lines[-1] = (last + "...") if last else "..."
    return font, lines


def _split_long_word(
    draw: ImageDraw.ImageDraw, word: str, font, max_width: int
) -> list[str]:
    if not word:
        return [word]
    if _text_size(draw, word, font)[0] <= max_width:
        return [word]
    parts: list[str] = []
    chunk = ""
    for ch in word:
        cand = chunk + ch
        if _text_size(draw, cand, font)[0] <= max_width:
            chunk = cand
        else:
            if chunk:
                parts.append(chunk)
                chunk = ch
            else:
                parts.append(ch)
                chunk = ""
    if chunk:
        parts.append(chunk)
    return parts


def _icon_cover_resize(icon: Image.Image, size: int) -> Image.Image:
    iw, ih = icon.size
    scale = max(size / iw, size / ih)
    nw, nh = int(math.ceil(iw * scale)), int(math.ceil(ih * scale))
    icon2 = icon.resize((nw, nh), Image.Resampling.LANCZOS)
    left = (nw - size) // 2
    top = (nh - size) // 2
    return icon2.crop((left, top, left + size, top + size))


def _trim_black_bbox(img: Image.Image, threshold: int = 18) -> Image.Image:
    img = img.convert("RGB")
    r, g, b = img.split()
    lum = ImageChops.add(ImageChops.add(r, g), b)
    mask = lum.point(lambda v: 255 if v > threshold * 3 else 0).convert("L")
    bbox = mask.getbbox()
    if not bbox:
        return img
    x0, y0, x1, y1 = bbox
    pad = 0
    x0 = max(0, x0 - pad)
    y0 = max(0, y0 - pad)
    x1 = min(img.width, x1 + pad)
    y1 = min(img.height, y1 + pad)
    return img.crop((x0, y0, x1, y1))


def _icon_contain_resize(icon: Image.Image, size: int, inner_pad: int) -> Image.Image:
    icon = icon.convert("RGBA")
    target = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    max_side = max(1, size - 2 * inner_pad)
    iw, ih = icon.size
    scale = min(max_side / iw, max_side / ih)
    nw, nh = max(1, int(round(iw * scale))), max(1, int(round(ih * scale)))
    icon2 = icon.resize((nw, nh), Image.Resampling.LANCZOS)
    ox = (size - nw) // 2
    oy = (size - nh) // 2
    target.alpha_composite(icon2, (ox, oy))
    return target


def _outer_rarity_glow_layer(size: tuple[int, int], rect: list[int], s: float, rarity_rgb):
    W, H = size
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    col1 = _mix((0, 0, 0), rarity_rgb, 0.90) + (110,)
    col2 = _mix((0, 0, 0), rarity_rgb, 0.75) + (70,)
    gd.rounded_rectangle(
        rect,
        radius=_px(18 * s, 1),
        outline=col1,
        width=_px(4 * s, 1),
    )
    gd.rounded_rectangle(
        [
            rect[0] + _px(2 * s),
            rect[1] + _px(2 * s),
            rect[2] - _px(2 * s),
            rect[3] - _px(2 * s),
        ],
        radius=_px(16 * s, 1),
        outline=col2,
        width=_px(3 * s, 1),
    )
    return glow.filter(ImageFilter.GaussianBlur(_px(3 * s, 1)))


def _draw_outer_ornaments(d: ImageDraw.ImageDraw, rect: list[int], s: float, rarity_rgb):
    x0, y0, x1, y1 = rect
    cx = (x0 + x1) // 2
    cy = (y0 + y1) // 2
    metal = (105, 108, 130)
    outline = _mix((40, 40, 52), metal, 0.35)
    line_color = (255, 255, 255, 160)

    def diamond(px, py, r, a=200):
        pts = [(px, py - r), (px + r, py), (px, py + r), (px - r, py)]
        d.polygon(pts, fill=metal + (a,), outline=outline + (a,))

    r = _px(8 * s, 1)
    top_off = _px(12 * s)
    diamond(cx, y0 + top_off, r)
    diamond(cx, y1 - _px(12 * s), r)

    w = _px(2 * s, 1)
    d.line(
        (cx - _px(24 * s), y0 + top_off, cx - _px(10 * s), y0 + top_off),
        fill=line_color,
        width=w,
    )
    d.line(
        (cx + _px(10 * s), y0 + top_off, cx + _px(24 * s), y0 + top_off),
        fill=line_color,
        width=w,
    )
    d.line(
        (
            cx - _px(24 * s),
            y1 - _px(12 * s),
            cx - _px(10 * s),
            y1 - _px(12 * s),
        ),
        fill=line_color,
        width=w,
    )
    d.line(
        (
            cx + _px(10 * s),
            y1 - _px(12 * s),
            cx + _px(24 * s),
            y1 - _px(12 * s),
        ),
        fill=line_color,
        width=w,
    )


def _draw_panel_inner_glow(
    img: Image.Image,
    box: tuple[int, int, int, int],
    s: float,
    rarity_rgb,
    strength: float,
):
    x0, y0, x1, y1 = box
    W, H = img.size
    mask = Image.new("L", (W, H), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle(
        [x0, y0, x1, y1],
        radius=_px(14 * s, 1),
        outline=255,
        width=_px(3 * s, 1),
    )
    mask = mask.filter(ImageFilter.GaussianBlur(_px(3 * s, 1)))
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    tint = _mix((0, 0, 0), rarity_rgb, 0.85)
    col = tint + (int(255 * strength),)
    gd.bitmap((0, 0), mask, fill=col)
    return Image.alpha_composite(img, glow)


def _draw_fancy_icon_frame(
    img: Image.Image,
    box: tuple[int, int, int, int],
    s: float,
    rarity_rgb,
    frame_width: int = 3,
):
    """Draw a frame around the icon that does NOT overlap the icon pixels.
    
    The frame starts exactly at the outer edge of the icon box.
    """
    x0, y0, x1, y1 = box
    d = ImageDraw.Draw(img)
    outer_col = (108, 110, 132)
    
    # Frame width in pixels (scaled)
    fw = _px(frame_width * s, 1)
    
    # Draw frame OUTSIDE the icon box (expand outward)
    # The rectangle outline is centered on the coordinates, so we need to offset
    frame_rect = [
        x0 - fw // 2,
        y0 - fw // 2,
        x1 + fw // 2,
        y1 + fw // 2,
    ]
    d.rectangle(frame_rect, outline=outer_col + (255,), width=fw)

    return img


def _draw_wrapped_panel_text(
    d: ImageDraw.ImageDraw, box, lines, font, fill, pad, line_gap
):
    x0, y0, x1, y1 = box
    if not lines:
        return
    max_w = (x1 - x0) - 2 * pad
    _, h = _text_size(d, "Ag", font)
    line_h = h + line_gap
    max_lines = max(1, ((y1 - y0) - 2 * pad) // line_h)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and _text_size(d, last + "...", font)[0] > max_w:
            last = last[:-1]
        lines[-1] = (last + "...") if last else "..."
    ty = y0 + pad
    for ln in lines:
        d.text((x0 + pad, ty), ln, font=font, fill=fill)
        ty += line_h


def _layout_measure(spec: ItemCardSpec, opts: RenderOptions, s: float):
    """Measure and layout all content for the item card.
    
    Layout order (top to bottom):
    - Header area: Icon (top-left), Title (big, max 3 lines), Rarity, Classes
    - Stats panel
    - Effects panel (if any)
    - Flavor text panel (if any)
    """
    W = _px(opts.width * s, 1)
    m = _px(opts.margin * s)
    pad = _px(opts.header_padding * s)
    
    # Card boundaries
    card_x0 = m
    card_y0 = m
    card_x1 = W - m
    
    tmp = Image.new("RGBA", (W, 10000), (0, 0, 0, 0))
    d = ImageDraw.Draw(tmp)

    # Fonts - sized for readability when 800px render is displayed at ~400px
    # These are "final" sizes that get multiplied by scale for rendering
    # At 800px width displayed at 400px (0.5x), these become ~14px displayed
    font_base = 0.5
    body_scale = max(0.5, float(opts.body_scale))
    title_scale = max(body_scale + 0.05, float(opts.title_scale))
    label_scale = max(0.4, float(opts.label_scale))
    label_font = _load_font(
        FONT_BOLD, max(1, int(round(24 * s * body_scale * label_scale * font_base)))
    )   # Rarity/Classes labels
    body_font = _load_font(FONT_REG, max(1, int(round(26 * s * body_scale * font_base))))     # Effects text
    stats_font = _load_font(FONT_BOLD, max(1, int(round(28 * s * body_scale * font_base))))   # Stats text
    flavor_font = _load_font(FONT_OBLIQUE, max(1, int(round(24 * s * body_scale * font_base))))  # Flavor text (italic, smaller)
    # Icon dimensions and position (top-left corner with padding)
    # Add extra space for the frame that will be drawn outside the icon
    frame_w = _px(opts.icon_frame_width * s)
    title_top = card_y0 + pad + frame_w
    line_gap = max(1, _px(6 * s * title_scale * font_base))  # Line gap

    rarity_key = (spec.rarity or "common").strip().lower()
    rarity_label = rarity_key.upper()
    level_label = f"Lvl {max(1, int(spec.level))}"
    _, rarity_h, rarity_y_off = _text_metrics(d, rarity_label, label_font)
    _, level_h, level_y_off = _text_metrics(d, level_label, label_font)

    if spec.classes and len(spec.classes) > 0:
        classes_text = ", ".join(spec.classes)
    else:
        classes_text = ""  # Empty means hide classes line

    def _header_for_icon(icon_size: int) -> dict:
        icon_x = card_x0 + pad + frame_w
        icon_y = title_top
        title_x = icon_x + icon_size + frame_w + pad
        title_max_w = max(1, card_x1 - title_x - pad)

        # Build visible labels bottom-up from text_container_bottom
        show_classes = bool(classes_text)
        classes_label = f"CLASSES: {classes_text}" if show_classes else ""
        if show_classes:
            if _text_size(d, classes_label, label_font)[0] > title_max_w:
                trimmed = classes_label
                while trimmed and _text_size(d, f"{trimmed}...", label_font)[0] > title_max_w:
                    trimmed = trimmed[:-1]
                classes_label = f"{trimmed}..." if trimmed else "..."
        _, classes_h, classes_y_off = _text_metrics(d, classes_label or "A", label_font)

        text_container_top = icon_y
        text_container_bottom = icon_y + icon_size + frame_w
        text_pad = max(1, _px(4 * s * body_scale))
        label_gap = max(_px(4 * s), _px(5 * s * body_scale))

        # Stack visible labels from bottom up
        cursor_bottom = text_container_bottom - text_pad

        if show_classes:
            classes_text_top = cursor_bottom - classes_h
            classes_y_val = classes_text_top - classes_y_off
            cursor_bottom = classes_text_top - label_gap
        else:
            classes_text_top = cursor_bottom
            classes_y_val = cursor_bottom
            classes_h = 0

        if spec.show_rarity:
            rarity_text_top = cursor_bottom - rarity_h
            rarity_y = rarity_text_top - rarity_y_off
            cursor_bottom = rarity_text_top - label_gap
        else:
            rarity_y = cursor_bottom

        if spec.show_level:
            level_text_top = cursor_bottom - level_h
            level_y = level_text_top - level_y_off
            cursor_bottom = level_text_top
        else:
            level_y = cursor_bottom

        title_rarity_gap = max(_px(8 * s), _px(10 * s * body_scale))
        title_area_top = text_container_top
        title_area_bottom = max(title_area_top + 1, cursor_bottom - title_rarity_gap)
        title_area_h = max(1, title_area_bottom - title_area_top)

        title_font, title_lines = fit_title(
            d,
            spec.title,
            title_max_w,
            max_lines=3,
            start_size=max(1, int(round(48 * s * title_scale * font_base))),
            min_size=max(1, int(round(24 * s * title_scale * font_base))),
            max_height=title_area_h,
            line_gap=line_gap,
        )
        if len(title_lines) > 1:
            title_font, title_lines = fit_title(
                d,
                spec.title,
                title_max_w,
                max_lines=3,
                start_size=max(1, int(round(42 * s * title_scale * font_base))),
                min_size=max(1, int(round(20 * s * title_scale * font_base))),
                max_height=title_area_h,
                line_gap=line_gap,
            )
        _, th = _text_size(d, "Ag", title_font)
        title_line_h = th + line_gap

        return {
            "icon_x": icon_x,
            "icon_y": icon_y,
            "icon_size": icon_size,
            "title_x": title_x,
            "title_max_w": title_max_w,
            "title_font": title_font,
            "title_lines": title_lines,
            "title_line_h": title_line_h,
            "level_label": level_label,
            "level_y": level_y,
            "level_h": level_h,
            "rarity_y": rarity_y,
            "classes_label": classes_label,
            "classes_y": classes_y_val,
            "classes_h": classes_h,
            "show_classes": show_classes,
        }

    icon_size = max(1, _px(84 * s))
    header = _header_for_icon(icon_size)

    icon_x = header["icon_x"]
    icon_y = header["icon_y"]
    icon_size = header["icon_size"]
    icon_frame_bottom = icon_y + icon_size + frame_w

    title_x = header["title_x"]
    title_max_w = header["title_max_w"]
    title_font = header["title_font"]
    title_lines = header["title_lines"]
    title_line_h = header["title_line_h"]

    level_label = header["level_label"]
    level_y = header["level_y"]
    level_h = header["level_h"]
    rarity_y = header["rarity_y"]
    classes_label = header["classes_label"]
    classes_y = header["classes_y"]
    classes_h = header["classes_h"]

    # Header bottom is fixed to the icon frame height for stable sizing
    header_bottom = icon_frame_bottom + pad

    # Content area for panels
    inset = _px(opts.content_inset * s)
    content_x0 = card_x0 + inset
    content_x1 = card_x1 - inset

    # Stats panel
    if not spec.stats:
        stat_lines = []
        stats_box_h = 0
        stat_line_gap = 0
    else:
        stat_lines = [f"{val} {name}".strip() for (val, name) in spec.stats]
        _, sh = _text_size(d, "Ag", stats_font)
        stat_line_gap = max(1, int(round(8 * s * body_scale * font_base)))
        stat_line_h = sh + stat_line_gap
        stats_pad_v = _px(16 * s)
        stats_desired_h = stats_pad_v * 2 + stat_line_h * len(stat_lines) - stat_line_gap
        stats_box_h = max(_px(72 * s), stats_desired_h)

    # Effects panel
    eff_lines, eff_box_h = [], 0
    if spec.effects:
        panel_pad = _px(14 * s)
        max_w = (content_x1 - content_x0) - 2 * panel_pad
        for i, eff in enumerate(spec.effects):
            bullet = "• " if len(spec.effects) > 1 else ""
            eff_lines.extend(wrap_text(d, f"{bullet}{eff}", body_font, max_w))
        body_line_gap = max(1, int(round(6 * s * body_scale * font_base)))
        _, bh = _text_size(d, "Ag", body_font)
        eff_box_h = panel_pad * 2 + (bh + body_line_gap) * len(eff_lines)

    # Flavor text panel
    fl_lines, fl_box_h = [], 0
    if spec.flavor_text:
        panel_pad = _px(14 * s)
        max_w = (content_x1 - content_x0) - 2 * panel_pad
        fl_lines = wrap_text(d, spec.flavor_text, flavor_font, max_w)
        body_line_gap = max(1, int(round(6 * s * body_scale * font_base)))
        _, fh = _text_size(d, "Ag", flavor_font)
        fl_box_h = panel_pad * 2 + (fh + body_line_gap) * max(1, len(fl_lines))

    return {
        "W": W,
        "m": m,
        "card_x0": card_x0,
        "card_y0": card_y0,
        "card_x1": card_x1,
        "icon_size": icon_size,
        "icon_x": icon_x,
        "icon_y": icon_y,
        "frame_w": frame_w,
        "content_x0": content_x0,
        "content_x1": content_x1,
        "fonts": {
            "label": label_font,
            "body": body_font,
            "stats": stats_font,
            "flavor": flavor_font,
            "title": title_font,
        },
        "title_lines": title_lines,
        "title_top": title_top,
        "title_line_h": title_line_h,
        "title_x": title_x,
        "title_max_w": title_max_w,
        "rarity_key": rarity_key,
        "level_label": level_label,
        "level_y": level_y,
        "level_h": level_h,
        "rarity_label": rarity_label,
        "rarity_y": rarity_y,
        "rarity_h": rarity_h,
        "classes_label": classes_label,
        "classes_y": classes_y,
        "classes_h": classes_h,
        "show_classes": header["show_classes"],
        "header_bottom": header_bottom,
        "stat_lines": stat_lines,
        "stats_box_h": stats_box_h,
        "stat_line_gap": stat_line_gap,
        "body_line_gap": max(1, int(round(6 * s * body_scale * font_base))),
        "eff_lines": eff_lines,
        "eff_box_h": eff_box_h,
        "fl_lines": fl_lines,
        "fl_box_h": fl_box_h,
    }


def _scale_box(box: tuple[int, int, int, int], scale: float):
    return (
        int(round(box[0] * scale)),
        int(round(box[1] * scale)),
        int(round(box[2] * scale)),
        int(round(box[3] * scale)),
    )


def render_item_card(
    spec: ItemCardSpec,
    opts: RenderOptions = RenderOptions(),
    downscale: bool = True,
) -> RenderedCard:
    s = max(1.0, float(opts.scale))
    layout = _layout_measure(spec, opts, s)

    W, m = layout["W"], layout["m"]
    card_x0, card_y0, card_x1 = layout["card_x0"], layout["card_y0"], layout["card_x1"]
    icon_x, icon_y = layout["icon_x"], layout["icon_y"]
    cx0, cx1 = layout["content_x0"], layout["content_x1"]

    content_bottom_safe = _px(opts.content_bottom_inset * s)
    panel_gap = _px(14 * s)

    # Calculate total height
    cursor_y = layout["header_bottom"]
    if layout["stats_box_h"] > 0:
        cursor_y += panel_gap + layout["stats_box_h"]
    if layout["eff_box_h"] > 0:
        cursor_y += panel_gap + layout["eff_box_h"]
    if layout["fl_box_h"] > 0:
        cursor_y += panel_gap + layout["fl_box_h"]

    H = (
        _px(opts.height * s, 1)
        if opts.height
        else int(round(cursor_y + content_bottom_safe + m))
    )

    rarity_rgb = RARITY_COLORS.get(layout["rarity_key"], RARITY_COLORS["common"])

    img = Image.new("RGBA", (W, H), opts.outside_bg + (opts.outside_alpha,))
    grad = _rarity_gradient(W, H, opts.base_bg, rarity_rgb)

    outer = [m, m, W - m, H - m]
    mask = Image.new("L", (W, H), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle(outer, radius=_px(18 * s, 1), fill=255)
    img = Image.composite(grad, img, mask)

    if opts.outer_rarity_glow:
        img = Image.alpha_composite(
            img, _outer_rarity_glow_layer(img.size, outer, s, rarity_rgb)
        )

    d = ImageDraw.Draw(img)
    d.rounded_rectangle(
        outer,
        radius=_px(18 * s, 1),
        outline=opts.border_color + (255,),
        width=_px(3 * s, 1),
    )
    inner = [
        outer[0] + _px(2 * s),
        outer[1] + _px(2 * s),
        outer[2] - _px(2 * s),
        outer[3] - _px(2 * s),
    ]
    d.rounded_rectangle(
        inner,
        radius=_px(16 * s, 1),
        outline=opts.border_soft + (255,),
        width=_px(1 * s, 1),
    )

    # Draw icon
    icon_size = layout["icon_size"]
    bg = _icon_gradient_bg(icon_size, rarity_rgb, opts.icon_bg_curve)
    img.alpha_composite(bg, (icon_x, icon_y))
    # Coverage: 100% if padding is disabled, otherwise use configured scale (default 90%)
    effective_scale = 1.0 if not spec.show_icon_padding else float(opts.icon_image_scale)
    icon_scale = max(0.1, min(1.0, effective_scale))
    
    icon_img_size = max(1, int(round(icon_size * icon_scale)))
    icon_img_x = icon_x + (icon_size - icon_img_size) // 2
    icon_img_y = icon_y + (icon_size - icon_img_size) // 2
    icon_path = _resolve_icon_path(spec.icon_path)
    if icon_path:
        try:
            icon = Image.open(icon_path)
            if opts.icon_trim_black and icon.size[0] != icon.size[1]:
                try:
                    icon = _trim_black_bbox(icon)
                except Exception:
                    pass
            icon = icon.convert("RGBA")
            if spec.show_icon_padding:
                # Padding enabled: Use contain mode at reduced scale
                icon_sq = _icon_contain_resize(icon, icon_img_size, inner_pad=0)
            else:
                # Padding disabled: Use cover mode at 100% scale
                icon_sq = _icon_cover_resize(icon, icon_img_size)
            img.alpha_composite(icon_sq, (icon_img_x, icon_img_y))
        except Exception:
            pass

    img = _draw_fancy_icon_frame(
        img,
        (icon_x, icon_y, icon_x + icon_size, icon_y + icon_size),
        s,
        rarity_rgb,
        opts.icon_frame_width,
    )
    d = ImageDraw.Draw(img)

    # Draw title (big text, rarity color)
    for i, ln in enumerate(layout["title_lines"]):
        d.text(
            (layout["title_x"], layout["title_top"] + i * layout["title_line_h"]),
            ln,
            font=layout["fonts"]["title"],
            fill=rarity_rgb,
        )
    
    # Draw level label above rarity
    if spec.show_level:
        d.text(
            (layout["title_x"], layout["level_y"]),
            layout["level_label"],
            font=layout["fonts"]["label"],
            fill=(185, 185, 200),
        )
    # Draw rarity label below level
    if spec.show_rarity:
        d.text(
            (layout["title_x"], layout["rarity_y"]),
            layout["rarity_label"],
            font=layout["fonts"]["label"],
            fill=(180, 180, 195),
        )
    
    # Draw classes below rarity (only if non-empty)
    if layout.get("show_classes"):
        d.text(
            (layout["title_x"], layout["classes_y"]),
            layout["classes_label"],
            font=layout["fonts"]["label"],
            fill=(175, 175, 190),
        )

    # Header divider line
    hb = layout["header_bottom"]
    d.line(
        (cx0, hb, cx1, hb),
        fill=opts.border_soft + (255,),
        width=_px(2 * s, 1),
    )
    acc = _mix(rarity_rgb, (255, 255, 255), 0.10)
    d.line(
        (cx0, hb + _px(3 * s), cx1, hb + _px(3 * s)),
        fill=acc + (80,),
        width=_px(1 * s, 1),
    )

    cursor_y = hb + panel_gap

    # Stats panel
    stats_box = None
    if layout["stats_box_h"] > 0:
        stats_box = (cx0, cursor_y, cx1, cursor_y + layout["stats_box_h"])
        d.rounded_rectangle(
            stats_box,
            radius=_px(14 * s, 1),
            fill=opts.panel_color + (255,),
            outline=opts.border_soft + (255,),
            width=_px(2 * s, 1),
        )
        if opts.panel_inner_glow:
            img = _draw_panel_inner_glow(img, stats_box, s, rarity_rgb, strength=0.25)
            d = ImageDraw.Draw(img)

        stats_font = layout["fonts"]["stats"]
        _, sh = _text_size(d, "Ag", stats_font)
        stat_line_h = sh + layout["stat_line_gap"]
        total_h = len(layout["stat_lines"]) * stat_line_h - layout["stat_line_gap"]
        sy = stats_box[1] + (layout["stats_box_h"] - total_h) // 2
        for ln in layout["stat_lines"]:
            lw, _ = _text_size(d, ln, stats_font)
            sx = stats_box[0] + ((stats_box[2] - stats_box[0]) - lw) // 2
            d.text((sx, sy), ln, font=stats_font, fill=opts.text_color + (255,))
            sy += stat_line_h

        cursor_y = stats_box[3] + panel_gap

    # Effects panel
    effects_box = None
    if layout["eff_box_h"] > 0:
        effects_box = (cx0, cursor_y, cx1, cursor_y + layout["eff_box_h"])
        d.rounded_rectangle(
            effects_box,
            radius=_px(14 * s, 1),
            fill=opts.panel_color + (255,),
            outline=opts.border_soft + (255,),
            width=_px(2 * s, 1),
        )
        if opts.panel_inner_glow:
            img = _draw_panel_inner_glow(img, effects_box, s, rarity_rgb, strength=0.18)
            d = ImageDraw.Draw(img)
        _draw_wrapped_panel_text(
            d,
            effects_box,
            layout["eff_lines"],
            layout["fonts"]["body"],
            opts.text_color + (255,),
            pad=_px(14 * s),
            line_gap=layout["body_line_gap"],
        )
        cursor_y = effects_box[3] + panel_gap

    # Flavor text panel
    flavor_box = None
    if layout["fl_box_h"] > 0:
        flavor_box = (cx0, cursor_y, cx1, cursor_y + layout["fl_box_h"])
        d.rounded_rectangle(
            flavor_box,
            radius=_px(14 * s, 1),
            fill=opts.panel_color + (255,),
            outline=opts.border_soft + (255,),
            width=_px(2 * s, 1),
        )
        if opts.panel_inner_glow:
            img = _draw_panel_inner_glow(img, flavor_box, s, rarity_rgb, strength=0.14)
            d = ImageDraw.Draw(img)
        _draw_wrapped_panel_text(
            d,
            flavor_box,
            layout["fl_lines"],
            layout["fonts"]["flavor"],
            (222, 222, 232, 255),
            pad=_px(14 * s),
            line_gap=layout["body_line_gap"],
        )

    d = ImageDraw.Draw(img)
    # Ornaments removed for cleaner look

    if downscale:
        out_h = max(1, int(round(H / s)))
        out = img.resize((opts.width, out_h), Image.Resampling.LANCZOS)
        scale = 1.0 / s
    else:
        out = img
        scale = 1.0
    
    # Build hitboxes
    title_box = (
        layout["title_x"],
        layout["title_top"],
        layout["title_x"] + layout["title_max_w"],
        layout["title_top"] + layout["title_line_h"] * len(layout["title_lines"]),
    )
    level_box = (
        layout["title_x"],
        layout["level_y"],
        layout["title_x"] + layout["title_max_w"],
        layout["level_y"] + layout["level_h"],
    )
    rarity_box = (
        layout["title_x"],
        layout["rarity_y"],
        layout["title_x"] + layout["title_max_w"],
        layout["rarity_y"] + layout["rarity_h"],
    )
    classes_box = (
        layout["title_x"],
        layout["classes_y"],
        layout["title_x"] + layout["title_max_w"],
        layout["classes_y"] + layout["classes_h"],
    )

    hitboxes = {
        "icon": (icon_x, icon_y, icon_x + icon_size, icon_y + icon_size),
        "title": title_box,
        "level": level_box,
        "rarity": rarity_box,
        "classes": classes_box,
    }
    if stats_box:
        hitboxes["stats"] = stats_box
    if effects_box:
        hitboxes["effects"] = effects_box
    if flavor_box:
        hitboxes["flavor"] = flavor_box

    hitboxes_out = {k: _scale_box(v, scale) for k, v in hitboxes.items()}
    return RenderedCard(out, hitboxes_out)


def spec_to_dict(spec: ItemCardSpec) -> Dict[str, object]:
    return {
        "title": spec.title,
        "rarity": spec.rarity,
        "classes": spec.classes,
        "stats": [[val, name] for val, name in spec.stats],
        "effects": list(spec.effects),
        "flavor_text": spec.flavor_text,
        "icon_path": spec.icon_path,
        "tags": list(spec.tags),
        "level": spec.level,
        "fused_stats_effects": spec.fused_stats_effects,
        "show_level": spec.show_level,
        "show_rarity": spec.show_rarity,
        "show_icon_padding": spec.show_icon_padding,
    }


def spec_from_dict(data: Dict[str, object]) -> ItemCardSpec:
    stats_raw = data.get("stats", []) or []
    stats: List[Tuple[str, str]] = []
    for pair in stats_raw:
        if isinstance(pair, (list, tuple)) and len(pair) >= 2:
            stats.append((str(pair[0]), str(pair[1])))
    # Handle classes - can be list, string, or None
    classes_raw = data.get("classes", [])
    if isinstance(classes_raw, str):
        # Legacy format: single string - convert to list or empty
        classes = [c.strip() for c in classes_raw.split(",") if c.strip() and c.strip().lower() != "all classes"]
    elif isinstance(classes_raw, list):
        classes = [str(c) for c in classes_raw if c]
    else:
        classes = []
    tags_raw = data.get("tags", []) or []
    if isinstance(tags_raw, str):
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
    elif isinstance(tags_raw, list):
        tags = [str(t).strip() for t in tags_raw if str(t).strip()]
    else:
        tags = []
    level_raw = data.get("level", 1)
    level = 1
    if isinstance(level_raw, (int, float)):
        level = int(level_raw)
    elif isinstance(level_raw, str):
        cleaned = level_raw.strip()
        if cleaned.isdigit():
            level = int(cleaned)
    if level < 1 or level > 20:
        level = 1
    return ItemCardSpec(
        title=str(data.get("title", "Untitled Item")),
        rarity=str(data.get("rarity", "uncommon")),
        classes=classes,
        stats=stats,
        effects=[str(x) for x in data.get("effects", []) or []],
        flavor_text=str(data.get("flavor_text", "") or ""),
        icon_path=data.get("icon_path") or None,
        tags=tags,
        level=level,
        fused_stats_effects=bool(data.get("fused_stats_effects", False)),
        show_level=bool(data.get("show_level", True)),
        show_rarity=bool(data.get("show_rarity", True)),
        show_icon_padding=bool(data.get("show_icon_padding", True)),
    )


def save_item_card_pdf(
    spec: ItemCardSpec,
    pdf_path: str,
    opts: Optional[RenderOptions] = None,
    pdf_resolution: int = 288,
    downscale: bool = False,
) -> RenderedCard:
    render_opts = opts or RenderOptions()
    rendered = render_item_card(spec, render_opts, downscale=downscale)
    rendered.image.convert("RGB").save(
        pdf_path,
        "PDF",
        resolution=pdf_resolution,
    )
    return rendered


def save_item_card_png(
    spec: ItemCardSpec,
    png_path: str,
    opts: Optional[RenderOptions] = None,
    png_resolution: int = 288,
    downscale: bool = False,
) -> RenderedCard:
    render_opts = opts or RenderOptions()
    rendered = render_item_card(spec, render_opts, downscale=downscale)
    rendered.image.save(
        png_path,
        "PNG",
        dpi=(png_resolution, png_resolution),
    )
    return rendered
