"""Parsing and validation of the supported IIIF Image API 3 subset.

Region:  full | x,y,w,h | pct:x,y,w,h
Size:    max | w, | ,h | !w,h   (upscaling is never allowed)
Rotation: [!](0|90|180|270)
Quality: default | gray
Format:  jpg | png
"""
import re
from dataclasses import dataclass


class BadRequest(Exception):
    pass


_NUM = r"\d+(?:\.\d+)?"
_REGION_RE = re.compile(rf"^(pct:)?({_NUM}),({_NUM}),({_NUM}),({_NUM})$")
_SIZE_RE = re.compile(rf"^(!)?({_NUM})?,({_NUM})?$")
_ROTATION_RE = re.compile(r"^(!)?(0|90|180|270)$")


def _to_float(text: str) -> float:
    value = float(text)
    if not (value == value and abs(value) != float("inf")):  # NaN/inf guard
        raise BadRequest("non-finite number")
    return value


@dataclass(frozen=True)
class Region:
    full: bool
    pct: bool
    x: float = 0.0
    y: float = 0.0
    w: float = 0.0
    h: float = 0.0

    def to_pixels(self, width: int, height: int):
        """Return (x, y, w, h) in pixels, clamped to the bottom/right edges.

        Raises BadRequest when the region is fully outside or has zero area.
        """
        if self.full:
            return 0, 0, width, height
        x, y, w, h = self.x, self.y, self.w, self.h
        if self.pct:
            x, y, w, h = x * width / 100, y * height / 100, w * width / 100, h * height / 100
        x, y = round(x), round(y)
        w, h = round(w), round(h)
        if w <= 0 or h <= 0:
            raise BadRequest("region has zero area")
        if x >= width or y >= height or x + w <= 0 or y + h <= 0:
            raise BadRequest("region is fully outside the image")
        x0, y0 = max(x, 0), max(y, 0)
        x1, y1 = min(x + w, width), min(y + h, height)
        return x0, y0, x1 - x0, y1 - y0


@dataclass(frozen=True)
class Size:
    kind: str  # "max" | "w" | "h" | "fit"
    w: int = 0
    h: int = 0

    def target(self, width: int, height: int):
        """Return output (w, h); never upscales."""
        if self.kind == "max":
            return width, height
        if self.kind == "w":
            tw = min(self.w, width)
            return tw, max(1, round(height * tw / width))
        if self.kind == "h":
            th = min(self.h, height)
            return max(1, round(width * th / height)), th
        # !w,h: best fit inside the box, no upscaling
        scale = min(self.w / width, self.h / height, 1.0)
        return max(1, round(width * scale)), max(1, round(height * scale))


@dataclass(frozen=True)
class Rotation:
    mirror: bool
    degrees: int


@dataclass(frozen=True)
class ImageRequest:
    image_id: str
    region: Region
    size: Size
    rotation: Rotation
    gray: bool
    fmt: str  # "jpg" | "png"

    @property
    def cache_token(self) -> str:
        r = self.region
        region = "full" if r.full else f"{'pct:' if r.pct else ''}{r.x},{r.y},{r.w},{r.h}"
        s = self.size
        size = {"max": "max", "w": f"{s.w},", "h": f",{s.h}", "fit": f"!{s.w},{s.h}"}[s.kind]
        rot = ("!" if self.rotation.mirror else "") + str(self.rotation.degrees)
        return f"{self.image_id}/{region}/{size}/{rot}/{'gray' if self.gray else 'default'}.{self.fmt}"


def parse_region(text: str) -> Region:
    if text == "full":
        return Region(full=True, pct=False)
    m = _REGION_RE.match(text)
    if not m:
        raise BadRequest(f"invalid region: {text!r}")
    pct = bool(m.group(1))
    x, y, w, h = (_to_float(g) for g in m.groups()[1:])
    if pct and (x > 100 or y > 100):
        raise BadRequest("pct region origin beyond 100%")
    return Region(full=False, pct=pct, x=x, y=y, w=w, h=h)


def parse_size(text: str) -> Size:
    if text == "max":
        return Size(kind="max")
    m = _SIZE_RE.match(text)
    if not m or not (m.group(2) or m.group(3)):
        raise BadRequest(f"invalid size: {text!r}")
    fit = bool(m.group(1))
    w = _to_float(m.group(2)) if m.group(2) else None
    h = _to_float(m.group(3)) if m.group(3) else None
    for v in (w, h):
        if v is not None and (v <= 0 or v > 1_000_000):
            raise BadRequest("size out of range")
    if fit:
        if w is None or h is None:
            raise BadRequest("! form requires both w and h")
        return Size(kind="fit", w=round(w), h=round(h))
    if w is not None:
        return Size(kind="w", w=round(w))
    return Size(kind="h", h=round(h))


def parse_rotation(text: str) -> Rotation:
    m = _ROTATION_RE.match(text)
    if not m:
        raise BadRequest(f"invalid rotation: {text!r}")
    return Rotation(mirror=bool(m.group(1)), degrees=int(m.group(2)))


def parse_quality(text: str) -> bool:
    if text == "default":
        return False
    if text == "gray":
        return True
    raise BadRequest(f"invalid quality: {text!r}")


def parse_format(text: str) -> str:
    if text in ("jpg", "png"):
        return text
    raise BadRequest(f"invalid format: {text!r}")


def parse_request(image_id: str, region: str, size: str, rotation: str, quality: str, fmt: str) -> ImageRequest:
    return ImageRequest(
        image_id=image_id,
        region=parse_region(region),
        size=parse_size(size),
        rotation=parse_rotation(rotation),
        gray=parse_quality(quality),
        fmt=parse_format(fmt),
    )

