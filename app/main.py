"""HTTP layer: IIIF Image API 3.0 (subset) routes, ETag handling, throttling."""

from __future__ import annotations

import asyncio
import hashlib

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from . import config, resources, transform
from .cache import DiskLRUCache

app = FastAPI(title="Collection IIIF Image Service")
cache = DiskLRUCache(config.CACHE_DIR, config.CACHE_MAX_BYTES)
_transform_slots = asyncio.Semaphore(config.MAX_PARALLEL_TRANSFORMS)

MEDIA_TYPES = {"jpg": "image/jpeg", "png": "image/png"}


@app.exception_handler(resources.ResourceError)
async def resource_error(_req: Request, exc: resources.ResourceError):
    return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})


@app.exception_handler(transform.BadRequest)
async def bad_request(_req: Request, exc: transform.BadRequest):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


def _etag_matches(request: Request, etag: str) -> bool:
    inm = request.headers.get("if-none-match")
    if not inm:
        return False
    return any(tag.strip() == etag or tag.strip() == "*" for tag in inm.split(","))


def _not_modified(etag: str) -> Response:
    return Response(status_code=304, headers={"ETag": etag})


@app.get("/iiif/3/{image_id}/info.json")
async def info(image_id: str, request: Request):
    ref = resources.resolve(image_id)
    width, height = await asyncio.to_thread(resources.source_dimensions, ref)
    body = {
        "@context": "http://iiif.io/api/image/3/context.json",
        "id": str(request.url_for("info", image_id=image_id)).removesuffix("/info.json"),
        "type": "ImageService3",
        "protocol": "http://iiif.io/api/image",
        "profile": "level1",
        "width": width,
        "height": height,
        "maxWidth": width,
        "maxHeight": height,
        "extraFeatures": ["mirroring", "regionByPct", "sizeByConfinedWh"],
        "extraQualities": ["gray"],
        "extraFormats": ["png"],
    }
    etag = '"%s"' % hashlib.sha256(
        f"info:{ref.image_id}:{ref.version}:{width}x{height}".encode()
    ).hexdigest()
    if _etag_matches(request, etag):
        return _not_modified(etag)
    return JSONResponse(content=body, headers={"ETag": etag}, media_type="application/ld+json")


def _derivative_key(ref: resources.SourceRef, params: str) -> str:
    return hashlib.sha256(f"{ref.image_id}:{ref.version}:{params}".encode()).hexdigest()


@app.get("/iiif/3/{image_id}/{region}/{size}/{rotation}/{quality}.{fmt}")
async def image_request(
    image_id: str, region: str, size: str, rotation: str, quality: str, fmt: str,
    request: Request,
):
    # Validate and normalize parameters before touching the cache so that
    # equivalent requests share one key.
    out_fmt = transform.parse_format(fmt)
    out_quality = transform.parse_quality(quality)
    mirror, degrees = transform.parse_rotation(rotation)

    ref = resources.resolve(image_id)
    src_w, src_h = await asyncio.to_thread(resources.source_dimensions, ref)
    reg = transform.parse_region(region, src_w, src_h)
    target = transform.parse_size(size, reg.w, reg.h)

    canonical = (
        f"{reg.x},{reg.y},{reg.w},{reg.h}/"
        f"{target[0]},{target[1]}/{'!' if mirror else ''}{degrees}/{out_quality}.{out_fmt}"
    )
    key = _derivative_key(ref, canonical)
    etag = f'"{key}"'
    if _etag_matches(request, etag):
        return _not_modified(etag)

    def factory() -> bytes:
        with resources.open_upright(ref) as src:
            out = transform.apply_transform(src, reg, target, mirror, degrees, out_quality, out_fmt)
            return transform.encode(out, out_fmt)

    async with _transform_slots:
        data = await asyncio.to_thread(cache.get_or_create, key, out_fmt, factory)
    return Response(
        content=data,
        media_type=MEDIA_TYPES[out_fmt],
        headers={"ETag": etag, "Cache-Control": "public, max-age=3600"},
    )
