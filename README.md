# Collection image delivery (IIIF Image API 3.0 subset)

Pure-backend image delivery for a collection viewer. Reads a local JSON
manifest, serves `info.json` and derived images over IIIF 3 style URLs.
No remote fetches, no uploads.

## Layout

- `app/config.py` — paths, cache capacity, decode/parallelism limits
- `app/resources.py` — manifest loading, safe path resolution (no symlinks,
  no root escape, PNG/JPEG only), EXIF-upright loading, source versioning
- `app/transform.py` — strict parameter parsing + pipeline
  (crop → scale → mirror → clockwise rotate → color)
- `app/cache.py` — capacity-bounded disk LRU, single-flight generation,
  atomic commits
- `app/main.py` — FastAPI routes, ETag / If-None-Match, transform throttling
- `scripts/make_samples.py` — sample images + `manifest.json`
- `scripts/demo.sh` — curl walkthrough
- `tests/test_api.py` — self-tests

## Run

```sh
.venv/bin/python scripts/make_samples.py   # once: sample images + manifest
.venv/bin/uvicorn app.main:app --port 8000
bash scripts/demo.sh                        # curl demo
.venv/bin/python -m pytest tests/ -q        # self-tests
```

## URL subset

```
GET /iiif/3/{id}/info.json
GET /iiif/3/{id}/{region}/{size}/{rotation}/{quality}.{format}
```

- region: `full` | `x,y,w,h` | `pct:x,y,w,h`
- size: `max` | `w,` | `,h` | `!w,h` (confined box; upscaling forbidden)
- rotation: `0|90|180|270`, optional `!` prefix for horizontal mirror
- quality: `default` | `gray`; format: `jpg` | `png`

## Boundaries & behavior

- Only files listed in `manifest.json` and located under `images/` are
  served; symlink components, `..` escapes, remote URLs and non-PNG/JPEG
  files are rejected (403/404).
- EXIF orientation is applied first; all dimensions/coordinates refer to the
  upright image.
- Regions overflowing the right/bottom edge are clipped; fully-outside or
  zero-area regions, malformed numbers, unsupported parameters → 400.
  Corrupt images → 400; decoded pixel count above `MAX_DECODE_PIXELS` → 413.
- Transparent pixels are composited on white for JPEG output.
- Derivatives are cached on disk under `.cache/derivatives` with a 64 MiB
  LRU cap. The cache key includes the source version (mtime+size), so an
  atomically replaced source immediately yields fresh info.json and fresh
  derivatives; in-flight work for the old version can never pollute the new
  one. Same-key concurrent requests generate once; failures leave no partial
  files and are retried by the next request.
- At most `MAX_PARALLEL_TRANSFORMS` (2) image computations run concurrently.
- All responses carry strong ETags; `If-None-Match` hits return an empty 304.

