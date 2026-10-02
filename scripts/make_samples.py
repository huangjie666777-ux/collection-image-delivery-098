"""Generate sample images and the manifest. Run: .venv/bin/python scripts/make_samples.py"""

import json
from pathlib import Path

from PIL import Image, ImageDraw

BASE = Path(__file__).resolve().parent.parent
IMAGES = BASE / "images"


def main() -> None:
    IMAGES.mkdir(exist_ok=True)

    # 800x600 RGB PNG with colored quadrants.
    im = Image.new("RGB", (800, 600))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, 399, 299], fill=(200, 30, 30))
    d.rectangle([400, 0, 799, 299], fill=(30, 200, 30))
    d.rectangle([0, 300, 399, 599], fill=(30, 30, 200))
    d.rectangle([400, 300, 799, 599], fill=(220, 220, 40))
    im.save(IMAGES / "quarters.png")

    # JPEG with EXIF orientation 6: stored 600x400, upright 400x600.
    jm = Image.new("RGB", (600, 400), (80, 120, 200))
    dj = ImageDraw.Draw(jm)
    dj.rectangle([0, 0, 599, 60], fill=(255, 255, 255))  # top band pre-rotation
    exif = Image.Exif()
    exif[274] = 6  # Orientation: rotate 90 CW to display
    jm.save(IMAGES / "rotated.jpg", exif=exif)

    # RGBA PNG with transparency (white compositing demo for JPEG export).
    am = Image.new("RGBA", (300, 200), (0, 0, 0, 0))
    da = ImageDraw.Draw(am)
    da.ellipse([50, 25, 250, 175], fill=(200, 40, 40, 255))
    am.save(IMAGES / "alpha.png")

    manifest = {
        "images": {
            "quarters": "quarters.png",
            "rotated": "rotated.jpg",
            "alpha": "alpha.png",
        }
    }
    (BASE / "manifest.json").write_text(json.dumps(manifest, indent=2) + chr(10))
    print("samples + manifest written")


if __name__ == "__main__":
    main()
