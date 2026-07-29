"""assets/app.ico ve assets/app.png dosyalarını üretir (yalnızca Pillow gerekir).

Kullanım:  python tools/make_icon.py
"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")

BG_TOP = (76, 141, 255)
BG_BOTTOM = (37, 99, 235)
PAPER = (255, 255, 255)
ACCENT = (229, 57, 53)
SIZE = 512


def rounded_gradient(size: int, radius: int) -> Image.Image:
    """Yuvarlatılmış köşeli dikey degrade arka plan."""
    grad = Image.new("RGB", (1, size))
    for y in range(size):
        t = y / max(1, size - 1)
        grad.putpixel(
            (0, y),
            tuple(int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3)),
        )
    grad = grad.resize((size, size))

    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius, fill=255)

    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(grad, (0, 0), mask)
    return out


def draw_icon() -> Image.Image:
    img = rounded_gradient(SIZE, int(SIZE * 0.22))
    d = ImageDraw.Draw(img)

    # sayfa gövdesi (sağ üst köşesi kıvrık)
    left, top, right, bottom = 128, 96, 384, 416
    fold = 74
    page = [
        (left, top),
        (right - fold, top),
        (right, top + fold),
        (right, bottom),
        (left, bottom),
    ]
    d.polygon(page, fill=PAPER)
    d.polygon(
        [(right - fold, top), (right, top + fold), (right - fold, top + fold)],
        fill=(214, 223, 240),
    )

    # metin satırları
    for i in range(4):
        y = 228 + i * 34
        d.rounded_rectangle([166, y, 346 - (60 if i == 3 else 0), y + 14], 7,
                            fill=(150, 163, 186))

    # PDF şeridi
    d.rounded_rectangle([150, 300, 300, 372], 14, fill=ACCENT)
    try:
        from PIL import ImageFont

        font = ImageFont.truetype("arialbd.ttf", 46)
    except Exception:  # noqa: BLE001
        font = None
    d.text((175, 316), "PDF", fill=PAPER, font=font)

    # kalem
    d.polygon([(300, 392), (392, 300), (424, 332), (332, 424), (292, 432)], fill=(255, 200, 60))
    d.polygon([(292, 432), (300, 392), (332, 424)], fill=(60, 60, 70))
    return img


def main() -> None:
    os.makedirs(ASSETS, exist_ok=True)
    img = draw_icon()
    png_path = os.path.join(ASSETS, "app.png")
    ico_path = os.path.join(ASSETS, "app.ico")
    app_icon_path = os.path.join(ASSETS, "app_icon.ico")
    img.save(png_path, "PNG")
    img.save(
        ico_path,
        "ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    img.save(
        app_icon_path,
        "ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print("yazıldı:", png_path)
    print("yazıldı:", ico_path)
    print("yazıldı:", app_icon_path)


if __name__ == "__main__":
    main()
