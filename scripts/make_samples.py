"""Generate sample images and the manifest. Run: .venv/bin/python scripts/make_samples.py"""
import json
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent / "data"
IMG = ROOT / "images"
IMG.mkdir(parents=True, exist_ok=True)


def checker(path, size, mode="RGB"):
    im = Image.new(mode, size)
    d = ImageDraw.Draw(im)
    step = 40
    for y in range(0, size[1], step):
        for x in range(0, size[0], step):
            c = (200, 60, 60) if (x // step + y // step) % 2 else (60, 120, 200)
            if mode == "RGBA":
                c = c + (128 if (x // step) % 2 else 255,)
            d.rectangle([x, y, x + step - 1, y + step - 1], fill=c)
    im.save(path)


checker(IMG / "photo.jpg", (1200, 800))
checker(IMG / "overlay.png", (600, 900), "RGBA")

(ROOT / "manifest.json").write_text(json.dumps({
    "images": [
        {"id": "photo", "path": "photo.jpg"},
        {"id": "overlay", "path": "overlay.png"},
    ]
}, indent=2))
print("samples written to", ROOT)

