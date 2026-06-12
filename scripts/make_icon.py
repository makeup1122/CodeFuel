"""Generate the CodeFuel app icon (assets/icon.ico + assets/icon.png).

Design "B": three stacked usage bars (orange / grey / blue) on a dark rounded
square — matching the tray glyph and panel bars. Rendered at 4x then downscaled
with LANCZOS for crisp small sizes.

Run: python scripts/make_icon.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

BG = (30, 30, 34, 255)       # #1e1e22  app background
BORDER = (52, 52, 60, 255)   # #34343c
TRACK = (58, 58, 66, 255)    # #3a3a42  bar track
ORANGE = (217, 119, 87, 255)  # Claude
GREY = (200, 200, 208, 255)   # Codex
BLUE = (77, 107, 254, 255)    # DeepSeek

# (vertical center fraction, colour, fill fraction)
BARS = [(0.355, ORANGE, 0.75), (0.5, GREY, 0.40), (0.645, BLUE, 0.62)]

ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]


def render(s: int) -> Image.Image:
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    radius = int(s * 0.225)
    d.rounded_rectangle(
        [0, 0, s - 1, s - 1], radius=radius, fill=BG,
        outline=BORDER, width=max(1, s // 128),
    )
    bx0, bx1 = s * 0.22, s * 0.78
    bw = bx1 - bx0
    bh = s * 0.085
    rad = bh / 2
    for cy_frac, color, frac in BARS:
        cy = s * cy_frac
        y0, y1 = cy - bh / 2, cy + bh / 2
        d.rounded_rectangle([bx0, y0, bx1, y1], radius=rad, fill=TRACK)
        fw = max(bh, bw * frac)  # never shorter than a single pill cap
        d.rounded_rectangle([bx0, y0, bx0 + fw, y1], radius=rad, fill=color)
    return img


def main() -> None:
    out = Path(__file__).resolve().parents[1] / "assets"
    out.mkdir(exist_ok=True)
    big = render(1024)
    base = big.resize((256, 256), Image.LANCZOS)
    base.save(out / "icon.png")
    base.save(out / "icon.ico", format="ICO", sizes=[(n, n) for n in ICO_SIZES])
    print(f"wrote {out / 'icon.png'} and {out / 'icon.ico'} ({ICO_SIZES})")


if __name__ == "__main__":
    main()
