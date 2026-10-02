"""HTTP layer: IIIF Image API 3 (subset) endpoints with ETag support."""
import asyncio
import hashlib
import json

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from .cache import DerivativeCache
from .config import settings
from .iiif import BadRequest, parse_request
from .manifest import ImageRepository, NotFoundError
from .transform import TooManyPixels, UnprocessableImage, load_oriented, render

app = FastAPI(title="Collection Image Service")
repo = ImageRepository(settings.image_root, settings.manifest_path)
cache = DerivativeCache(settings.cache_dir, settings.cache_max_bytes)
semaphore = asyncio.Semaphore(settings.max_parallel)

MEDIA_TYPES = {"jpg": "image/jpeg", "png": "image/png"}


@app.exception_handler(BadRequest)
async def bad_request(_req, exc):
    return JSONResponse(status_code=400, content={"error": str(exc)})


@app.exception_handler(NotFoundError)
async def not_found(_req, exc):
    return JSONResponse(status_code=404, content={"error": f"unknown image: {exc}"})


@app.exception_handler(UnprocessableImage)
async def broken(_req, exc):
    return JSONResponse(status_code=422, content={"error": str(exc)})


@app.exception_handler(TooManyPixels)
async def too_big(_req, exc):
    return JSONResponse(status_code=413, content={"error": str(exc)})


def _etag(*parts: str) -> str:
    return '"' + hashlib.sha256("|".join(parts).encode()).hexdigest()[:32] + '"'


def _if_none_match_hit(request: Request, etag: str) -> bool:
    inm = request.headers.get("if-none-match")
    if not inm:
        return False
    return any(tag.strip() == etag or tag.strip() == "*" for tag in inm.split(","))


@app.get("/iiif/3/{image_id}/info.json")
async def info(image_id: str, request: Request):
    src = repo.resolve(image_id)
    etag = _etag("info", src.image_id, src.version)
    headers = {"ETag": etag, "Cache-Control": "no-cache"}
    if _if_none_match_hit(request, etag):
        return Response(status_code=304, headers=headers)

    async with semaphore:
        im = await asyncio.to_thread(load_oriented, src.path, settings.max_pixels)
    body = {
        "@context": "http://iiif.io/api/image/3/context.json",
        "id": str(request.url_for("info", image_id=image_id)).replace("/info.json", ""),
        "type": "ImageService3",
        "protocol": "http://iiif.io/api/image",
        "profile": "level1",
        "width": im.width,
        "height": im.height,
        "maxWidth": im.width,
        "maxHeight": im.height,
        "extraFeatures": ["mirroring", "regionByPct", "sizeByConfinedWh"],
        "extraQualities": ["gray"],
        "extraFormats": ["png"],
    }
    return Response(content=json.dumps(body), media_type="application/ld+json", headers=headers)


@app.get("/iiif/3/{image_id}/{region}/{size}/{rotation}/{quality}.{fmt}")
async def image(image_id: str, region: str, size: str, rotation: str, quality: str, fmt: str, request: Request):
    req = parse_request(image_id, region, size, rotation, quality, fmt)
    src = repo.resolve(image_id)
    key = DerivativeCache.key_for(req.cache_token, src.version)
    etag = _etag("img", key)
    headers = {"ETag": etag, "Cache-Control": "no-cache"}
    if _if_none_match_hit(request, etag):
        return Response(status_code=304, headers=headers)

    data = cache.get(key)
    if data is None:
        lock = await cache.lock_for(key)
        async with lock:  # single-flight: equivalent requests render once
            try:
                data = cache.get(key)
                if data is None:
                    async with semaphore:
                        data = await asyncio.to_thread(render, src.path, req, settings.max_pixels)
                    cache.put(key, data)
            finally:
                await cache.release_lock(key)
    return Response(content=data, media_type=MEDIA_TYPES[req.fmt], headers=headers)

