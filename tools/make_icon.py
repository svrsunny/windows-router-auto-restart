"""Generate assets/router-auto-restart.ico (no third-party packages).

Draws the dashboard's logo - a rounded indigo square with a white Wi-Fi symbol - with 4x4
supersampling, and writes classic 32-bit DIB icon entries that Windows and Tk both read.

    python tools/make_icon.py
"""
from __future__ import annotations

import math
import struct
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "assets" / "router-auto-restart.ico"
SIZES = (16, 20, 24, 32, 40, 48, 64, 128)
BG = (79, 70, 229)          # #4f46e5
FG = (255, 255, 255)
SS = 4


def _in_rounded_square(x: float, y: float, m=0.03, r=0.24) -> bool:
    lo, hi = m, 1 - m
    if not (lo <= x <= hi and lo <= y <= hi):
        return False
    cx = min(max(x, lo + r), hi - r)
    cy = min(max(y, lo + r), hi - r)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def _in_symbol(x: float, y: float) -> bool:
    cx, cy, w = 0.5, 0.66, 0.075
    if (x - cx) ** 2 + (y - cy) ** 2 <= 0.068 ** 2:          # dot
        return True
    d = math.hypot(x - cx, y - cy)
    ang = math.degrees(math.atan2(cy - y, x - cx))
    for r in (0.22, 0.37):
        if abs(d - r) <= w / 2 and 45 <= ang <= 135:
            return True
        for a in (45, 135):                                      # round caps
            ex, ey = cx + r * math.cos(math.radians(a)), cy - r * math.sin(math.radians(a))
            if (x - ex) ** 2 + (y - ey) ** 2 <= (w / 2) ** 2:
                return True
    return False


def render(size: int) -> list[list[tuple[int, int, int, int]]]:
    rows = []
    for py in range(size):
        row = []
        for px in range(size):
            bg = fg = 0
            for sy in range(SS):
                for sx in range(SS):
                    x, y = (px + (sx + 0.5) / SS) / size, (py + (sy + 0.5) / SS) / size
                    if _in_rounded_square(x, y):
                        bg += 1
                        fg += _in_symbol(x, y)
            n = SS * SS
            a = bg / n
            t = fg / bg if bg else 0
            rgb = tuple(round(BG[i] * (1 - t) + FG[i] * t) for i in range(3))
            row.append((*rgb, round(a * 255)))
        rows.append(row)
    return rows


def dib(size: int) -> bytes:
    rows = render(size)
    pixels = b"".join(bytes((b, g, r, a)) for row in reversed(rows) for (r, g, b, a) in row)
    mask_row = ((size + 31) // 32) * 4
    mask = b"\x00" * (mask_row * size)
    header = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, len(pixels) + len(mask), 0, 0, 0, 0)
    return header + pixels + mask


def main() -> None:
    images = [dib(s) for s in SIZES]
    out = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    for s, img in zip(SIZES, images):
        out += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(img), offset)
        offset += len(img)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_bytes(out + b"".join(images))
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
