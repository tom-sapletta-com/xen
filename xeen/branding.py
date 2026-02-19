"""Watermark and branding support for xeen exports.

Reads config from ~/.xeen/branding.json:
{
  "logo": "/path/to/logo.png",       // optional logo overlay
  "logo_position": "bottom_right",   // top_left, top_right, bottom_left, bottom_right
  "logo_size": 64,                   // max width/height in px
  "logo_opacity": 0.7,               // 0.0 - 1.0
  "footer_text": "example.com",      // text at bottom
  "footer_font_size": 18,
  "footer_color": "#ffffff",
  "footer_bg": "#00000080"           // RGBA hex
}
"""

import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

from xeen.config import get_data_dir

DEFAULT_BRANDING = {
    "logo": None,
    "logo_position": "bottom_right",
    "logo_size": 64,
    "logo_opacity": 0.7,
    "footer_text": None,
    "footer_font_size": 18,
    "footer_color": "#ffffff",
    "footer_bg": "#00000080",
}


def load_branding() -> dict:
    """Load branding config from ~/.xeen/branding.json, merged with defaults."""
    config_path = get_data_dir() / "branding.json"
    branding = dict(DEFAULT_BRANDING)
    if config_path.exists():
        try:
            user = json.loads(config_path.read_text())
            branding.update(user)
        except (json.JSONDecodeError, OSError):
            pass
    return branding


def apply_watermark(img: Image.Image, branding: dict | None = None) -> Image.Image:
    """Apply watermark/branding to a PIL Image. Returns new image."""
    if branding is None:
        branding = load_branding()

    img = img.copy().convert("RGBA")
    iw, ih = img.size

    # ── Logo overlay ──
    logo_path = branding.get("logo")
    if logo_path and Path(logo_path).exists():
        try:
            logo = Image.open(logo_path).convert("RGBA")
            max_size = branding.get("logo_size", 64)
            logo.thumbnail((max_size, max_size), Image.LANCZOS)

            # Apply opacity
            opacity = branding.get("logo_opacity", 0.7)
            if opacity < 1.0:
                alpha = logo.split()[3]
                alpha = alpha.point(lambda p: int(p * opacity))
                logo.putalpha(alpha)

            # Position
            lw, lh = logo.size
            margin = 12
            pos = branding.get("logo_position", "bottom_right")
            px_frac = branding.get("logo_position_x")
            py_frac = branding.get("logo_position_y")
            if pos == "custom" and px_frac is not None and py_frac is not None:
                px = int(px_frac * iw) - lw // 2
                py = int(py_frac * ih) - lh // 2
            else:
                positions = {
                    "top_left":     (margin, margin),
                    "top_right":    (iw - lw - margin, margin),
                    "bottom_left":  (margin, ih - lh - margin),
                    "bottom_right": (iw - lw - margin, ih - lh - margin),
                    "center":       ((iw - lw) // 2, (ih - lh) // 2),
                }
                px, py = positions.get(pos, positions["bottom_right"])
            px = max(0, min(px, iw - lw))
            py = max(0, min(py, ih - lh))
            img.paste(logo, (px, py), logo)
        except Exception:
            pass

    # ── Footer text ──
    footer = branding.get("footer_text")
    if footer:
        draw = ImageDraw.Draw(img)
        font_size = branding.get("footer_font_size", 18)

        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
        except (OSError, IOError):
            try:
                font = ImageFont.truetype("/usr/share/fonts/TTF/DejaVuSans-Bold.ttf", font_size)
            except (OSError, IOError):
                font = ImageFont.load_default()

        bbox = draw.textbbox((0, 0), footer, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        padding = 8

        # Background bar
        bg_color = branding.get("footer_bg", "#00000080")
        # Parse RGBA hex
        if len(bg_color) == 9:  # #RRGGBBAA
            r = int(bg_color[1:3], 16)
            g = int(bg_color[3:5], 16)
            b = int(bg_color[5:7], 16)
            a = int(bg_color[7:9], 16)
            bg_rgba = (r, g, b, a)
        else:
            bg_rgba = (0, 0, 0, 128)

        bar_y = ih - th - padding * 2
        overlay = Image.new("RGBA", (iw, ih), (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        overlay_draw.rectangle([(0, bar_y), (iw, ih)], fill=bg_rgba)
        img = Image.alpha_composite(img, overlay)

        # Text
        draw = ImageDraw.Draw(img)
        text_color = branding.get("footer_color", "#ffffff")
        tx = (iw - tw) // 2
        ty = bar_y + padding
        draw.text((tx, ty), footer, fill=text_color, font=font)

    return img.convert("RGB")


def init_branding_config():
    """Create a default branding.json if it doesn't exist."""
    config_path = get_data_dir() / "branding.json"
    if not config_path.exists():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        example = {
            "logo": None,
            "logo_position": "bottom_right",
            "logo_size": 64,
            "logo_opacity": 0.7,
            "footer_text": None,
            "footer_font_size": 18,
            "footer_color": "#ffffff",
            "footer_bg": "#00000080",
        }
        config_path.write_text(json.dumps(example, indent=2))
    return config_path
