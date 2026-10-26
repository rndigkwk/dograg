"""Draw the web app's dog icon from one shape list: icon.svg, favicon.ico (16/32/48) and apple-icon.png (180).

    python scripts/make_favicon.py web/src/app [PREVIEW_DIR]
"""
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw

out = Path(sys.argv[1])
BG, EAR, FACE, INK, TONGUE = "#0f6e63", "#b97a3f", "#fff6e9", "#14231f", "#e36d6d"

# (kind, params, fill) on a 64 grid; ellipses may be rotated (degrees).
SHAPES = [
    ("ellipse", (14.5, 34, 7.5, 14, 14), EAR),
    ("ellipse", (49.5, 34, 7.5, 14, -14), EAR),
    ("ellipse", (32, 35, 17, 18, 0), FACE),
    ("ellipse", (32, 45, 9.5, 7.5, 0), "#ffffff"),
    ("ellipse", (24.5, 32, 2.8, 3.2, 0), INK),
    ("ellipse", (39.5, 32, 2.8, 3.2, 0), INK),
    ("ellipse", (32, 41, 4, 3, 0), INK),
    ("ellipse", (32, 51, 2.4, 2.6, 0), TONGUE),
]


def svg() -> str:
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">',
             f'<rect width="64" height="64" rx="14" fill="{BG}"/>']
    for _, (cx, cy, rx, ry, angle), fill in SHAPES:
        rotate = f' transform="rotate({angle} {cx} {cy})"' if angle else ""
        parts.append(f'<ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}" fill="{fill}"{rotate}/>')
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def raster(size: int, rounded: bool = True) -> Image.Image:
    scale = 8
    big = size * scale
    k = big / 64
    image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, big - 1, big - 1), radius=(14 * k if rounded else 0), fill=BG)
    for _, (cx, cy, rx, ry, angle), fill in SHAPES:
        a = math.radians(angle)
        points = []
        for i in range(120):
            t = 2 * math.pi * i / 120
            x, y = rx * math.cos(t), ry * math.sin(t)
            points.append(((cx + x * math.cos(a) - y * math.sin(a)) * k, (cy + x * math.sin(a) + y * math.cos(a)) * k))
        draw.polygon(points, fill=fill)
    return image.resize((size, size), Image.LANCZOS)


(out / "icon.svg").write_text(svg(), encoding="utf-8")
raster(48).save(out / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
raster(180, rounded=False).save(out / "apple-icon.png")  # iOS rounds the corners itself
if len(sys.argv) > 2:
    raster(256).save(Path(sys.argv[2]) / "preview.png")
