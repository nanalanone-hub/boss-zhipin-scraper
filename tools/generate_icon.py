#!/usr/bin/env python3
"""Generate a local icon for the desktop tool without committing a binary asset."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"


def draw_icon(size: int = 256):
    image = Image.new("RGBA", (size, size), (15, 76, 129, 255))
    draw = ImageDraw.Draw(image)
    margin = size * 0.12
    draw.rounded_rectangle(
        (margin, margin * 1.05, size - margin, size - margin * 1.05),
        radius=size * 0.12,
        fill=(255, 255, 255, 255),
    )
    bar_color = (15, 76, 129, 255)
    x1, x2 = size * 0.24, size * 0.76
    ys = [0.30, 0.47, 0.64, 0.78]
    heights = [0.075, 0.075, 0.075, 0.055]
    widths = [1.0, 0.78, 0.62, 0.88]
    for y, height, width in zip(ys, heights, widths):
        draw.rounded_rectangle(
            (x1, size * y, x1 + (x2 - x1) * width, size * (y + height)),
            radius=size * 0.018,
            fill=bar_color,
        )
    return image


def main():
    ASSETS.mkdir(parents=True, exist_ok=True)
    icon = draw_icon()
    icon.save(ASSETS / "boss-collector.png")
    icon.save(ASSETS / "boss-collector.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(ASSETS / "boss-collector.ico")


if __name__ == "__main__":
    main()
