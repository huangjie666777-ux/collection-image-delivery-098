"""IIIF parameter parsing and the image transform pipeline.

Pipeline order: crop -> scale -> mirror -> clockwise rotation -> color.
Upscaling is forbidden. All numeric parsing is strict; anything malformed
raises BadRequest (HTTP 400).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from PIL import Image


class BadRequest(Exception):
    pass


_INT_RE = re.compile(r"^\d+$")
_NUM_RE = re.compile(r"^\d+(?:\.d+)?$")


def _parse_int(token: str, what: str) -> int:
    if not _INT_RE.match(token):
        raise BadRequest(f"invalid {what}: {token!r}")
    return int(token)


def _parse_float(token: str, what: str) -> float:
    if not _NUM_RE.match(token):
        raise BadRequest(f"invalid {what}: {token!r}")
    return float(token)


@dataclass(frozen=True)
class Region:
    x: int
    y: int
    w: int
    h: int


def parse_region(region: str, src_w: int, src_h: int) -> Region:
    """Parse a region parameter against the upright source dimensions.

    Regions overflowing the right/bottom edge are clipped; regions fully
    outside or with zero area are rejected.
    """
    if region == "full":
        return Region(0, 0, src_w, src_h)
    if region.startswith("pct:"):
        parts = region[4:].split(",")
        if len(parts) != 4:
            raise BadRequest("pct region needs 4 numbers")
        px, py, pw, ph = (_parse_float(p, "pct region") for p in parts)
        x = int(round(src_w * px / 100.0))
        y = int(round(src_h * py / 100.0))
        w = int(round(src_w * pw / 100.0))
        h = int(round(src_h * ph / 100.0))
    else:
        parts = region.split(",")
        if len(parts) != 4:
            raise BadRequest("region must be 'full', 'x,y,w,h' or 'pct:x,y,w,h'")
        x, y, w, h = (_parse_int(p, "region") for p in parts)
    if w <= 0 or h <= 0:
        raise BadRequest("region has zero area")
    if x >= src_w or y >= src_h:
        raise BadRequest("region lies fully outside the image")
    w = min(w, src_w - x)
    h = min(h, src_h - y)
    if w <= 0 or h <= 0:
        raise BadRequest("region has zero area")
    return Region(x, y, w, h)


def parse_size(size: str, reg_w: int, reg_h: int) -> tuple[int, int]:
    """Parse a size parameter into target (width, height). No upscaling."""
    if size == "max":
        return reg_w, reg_h
    if size.startswith("!"):
        parts = size[1:].split(",")
        if len(parts) != 2:
            raise BadRequest("!w,h needs two numbers")
        bw = _parse_int(parts[0], "size width")
        bh = _parse_int(parts[1], "size height")
        if bw <= 0 or bh <= 0:
            raise BadRequest("size must be positive")
        scale = min(bw / reg_w, bh / reg_h, 1.0)  # never upscale
        return max(1, round(reg_w * scale)), max(1, round(reg_h * scale))
    parts = size.split(",")
    if len(parts) != 2:
        raise BadRequest("unsupported size form")
    w_tok, h_tok = parts
    if w_tok and not h_tok:
        w = _parse_int(w_tok, "size width")
        if w <= 0:
            raise BadRequest("size must be positive")
        if w > reg_w:
            raise BadRequest("upscaling is not allowed")
        return w, max(1, round(reg_h * w / reg_w))
    if h_tok and not w_tok:
        h = _parse_int(h_tok, "size height")
        if h <= 0:
            raise BadRequest("size must be positive")
        if h > reg_h:
            raise BadRequest("upscaling is not allowed")
        return max(1, round(reg_w * h / reg_h)), h
    raise BadRequest("exact w,h sizes are not supported; use max, w, ,h or !w,h")


def parse_rotation(rotation: str) -> tuple[bool, int]:
    """Return (mirror, degrees). Degrees are clockwise: 0/90/180/270."""
    mirror = rotation.startswith("!")
    token = rotation[1:] if mirror else rotation
    if token not in ("0", "90", "180", "270"):
        raise BadRequest(f"unsupported rotation: {rotation!r}")
    return mirror, int(token)


def parse_quality(quality: str) -> str:
    if quality not in ("default", "gray"):
        raise BadRequest(f"unsupported quality: {quality!r}")
    return quality


def parse_format(fmt: str) -> str:
    if fmt not in ("jpg", "png"):
        raise BadRequest(f"unsupported format: {fmt!r}")
    return fmt


def apply_transform(
    src: Image.Image,
    region: Region,
    size: tuple[int, int],
    mirror: bool,
    degrees: int,
    quality: str,
    fmt: str,
) -> Image.Image:
    """Crop -> scale -> mirror -> rotate clockwise -> color."""
    im = src.crop((region.x, region.y, region.x + region.w, region.y + region.h))
    if im.size != size:
        im = im.resize(size, Image.LANCZOS)
    if mirror:
        im = im.transpose(Image.FLIP_LEFT_RIGHT)
    if degrees:
        # PIL rotates counter-clockwise; negate for clockwise.
        im = im.transpose({90: Image.ROTATE_270, 180: Image.ROTATE_180, 270: Image.ROTATE_90}[degrees])
    if quality == "gray":
        im = im.convert("L")
    if fmt == "jpg":
        if im.mode in ("RGBA", "LA", "P"):
            rgba = im.convert("RGBA")
            background = Image.new("RGB", rgba.size, (255, 255, 255))
            background.paste(rgba, mask=rgba.getchannel("A"))
            im = background
        elif im.mode != "RGB" and im.mode != "L":
            im = im.convert("RGB")
    return im


def encode(im: Image.Image, fmt: str) -> bytes:
    import io

    buf = io.BytesIO()
    if fmt == "jpg":
        im.save(buf, "JPEG", quality=85)
    else:
        im.save(buf, "PNG")
    return buf.getvalue()
