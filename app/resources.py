"""Resource resolution: manifest loading, safe path resolution, image loading.

Only PNG/JPEG files inside IMAGE_ROOT are reachable. Symlinks and any path
escaping the root are rejected. EXIF orientation is applied on load so all
dimensions and coordinates refer to the upright image.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps

from . import config

Image.MAX_IMAGE_PIXELS = config.MAX_DECODE_PIXELS

ALLOWED_SUFFIXES = {".png", ".jpg", ".jpeg"}


class ResourceError(Exception):
    """Base class for resource resolution failures (maps to HTTP errors)."""

    status_code = 400


class NotFoundError(ResourceError):
    status_code = 404


class ForbiddenError(ResourceError):
    status_code = 403


class CorruptImageError(ResourceError):
    status_code = 400


class TooLargeError(ResourceError):
    status_code = 413


@dataclass(frozen=True)
class SourceRef:
    image_id: str
    path: Path
    version: tuple  # (mtime_ns, size) — changes on atomic source replacement


_manifest_lock = threading.Lock()
_manifest_cache: tuple[float, dict[str, str]] | None = None


def _load_manifest() -> dict[str, str]:
    global _manifest_cache
    mtime = os.path.getmtime(config.MANIFEST_PATH)
    with _manifest_lock:
        if _manifest_cache and _manifest_cache[0] == mtime:
            return _manifest_cache[1]
        with open(config.MANIFEST_PATH, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        images = raw.get("images")
        if not isinstance(images, dict):
            raise ResourceError("manifest must contain an 'images' object")
        _manifest_cache = (mtime, dict(images))
        return _manifest_cache[1]


def _resolve_safe(rel_path: str) -> Path:
    if not isinstance(rel_path, str) or not rel_path:
        raise ForbiddenError("empty path")
    if "://" in rel_path or rel_path.startswith(("//", "\\")):
        raise ForbiddenError("remote addresses are not allowed")
    root = config.IMAGE_ROOT
    candidate = root / rel_path
    # Reject any symlink component between root and the file itself.
    probe = root
    for part in Path(rel_path).parts:
        probe = probe / part
        if probe.is_symlink():
            raise ForbiddenError("symlinks are not allowed")
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError:
        raise NotFoundError("image file not found")
    if not resolved.is_file():
        raise NotFoundError("image file not found")
    if resolved.suffix.lower() not in ALLOWED_SUFFIXES:
        raise ForbiddenError("only PNG and JPEG images are served")
    if os.path.commonpath([str(root.resolve()), str(resolved)]) != str(root.resolve()):
        raise ForbiddenError("path escapes the image root")
    return resolved


def resolve(image_id: str) -> SourceRef:
    """Resolve an image ID to a versioned on-disk source, or raise."""
    manifest = _load_manifest()
    rel = manifest.get(image_id)
    if rel is None:
        raise NotFoundError(f"unknown image id: {image_id!r}")
    path = _resolve_safe(rel)
    st = path.stat()
    return SourceRef(image_id=image_id, path=path, version=(st.st_mtime_ns, st.st_size))


def open_upright(ref: SourceRef) -> Image.Image:
    """Open the source image with EXIF orientation applied (fully loaded)."""
    try:
        with Image.open(ref.path) as im:
            upright = ImageOps.exif_transpose(im)
            upright.load()
            return upright
    except Image.DecompressionBombError as exc:
        raise TooLargeError("decoded image exceeds pixel limit") from exc
    except Exception as exc:  # UnidentifiedImageError, OSError, truncated data...
        raise CorruptImageError(f"cannot decode image: {exc}") from exc


_info_lock = threading.Lock()
_info_cache: dict[tuple[str, tuple], tuple[int, int]] = {}


def source_dimensions(ref: SourceRef) -> tuple[int, int]:
    """(width, height) of the upright source, cached per source version."""
    key = (str(ref.path), ref.version)
    with _info_lock:
        dims = _info_cache.get(key)
    if dims is None:
        with open_upright(ref) as im:
            dims = im.size
        with _info_lock:
            # Bound the cache; versions change on replacement.
            if len(_info_cache) > 512:
                _info_cache.clear()
            _info_cache[key] = dims
    return dims
