#!/usr/bin/env bash
# Curl demo against a locally running server (start with:
#   .venv/bin/uvicorn app.main:app --port 8000)
set -euo pipefail
B=http://localhost:8000/iiif/3

echo '--- info.json (EXIF-corrected 400x600)'
curl -s "$B/rotated/info.json" | python3 -m json.tool

echo '--- full region, max size, default quality, png'
curl -s -o /tmp/full.png -w '%{http_code} %{content_type} %{size_download}B\n' \
  "$B/quarters/full/max/0/default.png"

echo '--- pixel region clipped at the right/bottom edge'
curl -s -o /tmp/clipped.jpg -w '%{http_code} %{content_type}\n' \
  "$B/quarters/700,500,400,400/max/0/default.jpg"

echo '--- pct region + confined !w,h + mirror + 90 CW rotation + gray'
curl -s -o /tmp/gray.jpg -w '%{http_code} %{content_type}\n' \
  "$B/quarters/pct:10,10,50,50/!200,200/!90/gray.jpg"

echo '--- transparent PNG exported as JPEG (white background)'
curl -s -o /tmp/alpha.jpg -w '%{http_code} %{content_type}\n' \
  "$B/alpha/full/max/0/default.jpg"

echo '--- ETag / If-None-Match -> 304'
ETAG=$(curl -s -D - -o /dev/null "$B/quarters/full/max/0/default.png" | awk 'tolower($1)=="etag:"{print $2}' | tr -d '\r')
curl -s -o /dev/null -w '%{http_code}\n' -H "If-None-Match: $ETAG" \
  "$B/quarters/full/max/0/default.png"

echo '--- errors: 400 upscaling / 400 outside region / 400 bad numbers / 404 unknown id'
curl -s -o /dev/null -w '%{http_code}\n' "$B/quarters/full/2000,/0/default.jpg"
curl -s -o /dev/null -w '%{http_code}\n' "$B/quarters/900,0,10,10/max/0/default.jpg"
curl -s -o /dev/null -w '%{http_code}\n' "$B/quarters/0,0,-5,10/max/0/default.jpg"
curl -s -o /dev/null -w '%{http_code}\n' "$B/nope/full/max/0/default.jpg"
