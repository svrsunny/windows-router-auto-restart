"""Generate the app's launcher and notification icons from the project logo.

Uses the drawing functions of the PC app's tools/make_icon.py (rounded indigo square with a white
Wi-Fi symbol), so the phone and PC apps share one logo. Needs Pillow only for writing PNGs.

    python android/tools/make_icons.py            # from the repository root
"""
import importlib.util
import sys
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
RES = HERE.parent / "app" / "res"
LOGO = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE.parent.parent / "tools" / "make_icon.py"

spec = importlib.util.spec_from_file_location("make_icon", LOGO)
logo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(logo)
BG, FG = logo.BG, logo.FG
SS = 4


def render(size, inside, color, to_unit):
    """Anti-aliased RGBA image: `inside(u, v)` tested on SSxSS samples per pixel, mapped by `to_unit`."""
    img = Image.new("RGBA", (size, size))
    px = []
    for y in range(size):
        for x in range(size):
            hits = 0
            for sy in range(SS):
                for sx in range(SS):
                    u, v = to_unit((x + (sx + 0.5) / SS) / size, (y + (sy + 0.5) / SS) / size)
                    hits += inside(u, v)
            px.append(color + (round(255 * hits / (SS * SS)),))
    img.putdata(px)
    return img


identity = lambda u, v: (u, v)                                          # noqa: E731
# adaptive icons are 108 dp (a 66 dp circle is always visible): draw the logo's unit square over the
# middle 84 dp, which puts the Wi-Fi symbol (about 49 x 40 dp) inside that circle
adaptive = lambda u, v: ((u * 108 - 12) / 84, (v * 108 - 12) / 84)      # noqa: E731
# notification icons: the Wi-Fi symbol (about u 0.21-0.79, v 0.25-0.73) enlarged to fill the 24 dp box
status = lambda u, v: (0.5 + (u - 0.5) * 0.68, 0.49 + (v - 0.5) * 0.68)  # noqa: E731


def write(img, folder, name):
    out = RES / folder
    out.mkdir(parents=True, exist_ok=True)
    img.save(out / name)


for d, size in {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}.items():
    tile = render(size, logo._in_rounded_square, BG, identity)
    tile.alpha_composite(render(size, logo._in_symbol, FG, identity))
    write(tile, f"mipmap-{d}", "ic_launcher.png")

write(Image.new("RGBA", (432, 432), BG + (255,)), "mipmap-xxxhdpi", "ic_launcher_bg.png")
write(render(432, logo._in_symbol, FG, adaptive), "mipmap-xxxhdpi", "ic_launcher_fg.png")
(RES / "mipmap-anydpi-v26").mkdir(parents=True, exist_ok=True)
(RES / "mipmap-anydpi-v26" / "ic_launcher.xml").write_text(
    '<?xml version="1.0" encoding="utf-8"?>\n'
    '<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">\n'
    '    <background android:drawable="@mipmap/ic_launcher_bg" />\n'
    '    <foreground android:drawable="@mipmap/ic_launcher_fg" />\n'
    '</adaptive-icon>\n', encoding="utf-8")

for d, size in {"mdpi": 24, "hdpi": 36, "xhdpi": 48, "xxhdpi": 72, "xxxhdpi": 96}.items():
    write(render(size, logo._in_symbol, FG, status), f"drawable-{d}", "ic_stat_router.png")
print("icons written to", RES)
