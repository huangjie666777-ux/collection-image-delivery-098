import io
import json
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.main import app, cache  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def samples():
    from scripts.make_samples import main as make
    make()
    cache.clear()


@pytest.fixture()
def client():
    return TestClient(app)


def open_image(resp):
    return Image.open(io.BytesIO(resp.content))


def restore_manifest():
    from scripts.make_samples import main as make
    make()


def test_info_reports_upright_dimensions(client):
    r = client.get("/iiif/3/rotated/info.json")
    assert r.status_code == 200
    body = r.json()
    assert (body["width"], body["height"]) == (400, 600)  # EXIF applied
    assert body["type"] == "ImageService3"
    assert "gray" in body["extraQualities"]
    assert "ETag" in r.headers


def test_full_max_png(client):
    r = client.get("/iiif/3/quarters/full/max/0/default.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert open_image(r).size == (800, 600)


def test_pixel_region_clipped_to_edges(client):
    r = client.get("/iiif/3/quarters/700,500,400,400/max/0/default.jpg")
    assert r.status_code == 200
    assert open_image(r).size == (100, 100)  # clipped, not an error


def test_pct_region_and_size_by_width(client):
    r = client.get("/iiif/3/quarters/pct:0,0,50,50/100,/0/default.jpg")
    assert r.status_code == 200
    assert open_image(r).size == (100, 75)


def test_size_by_height_and_confined_box(client):
    r = client.get("/iiif/3/quarters/full/,150/0/default.jpg")
    assert open_image(r).size == (200, 150)
    r = client.get("/iiif/3/quarters/full/!250,250/0/default.jpg")
    assert open_image(r).size == (250, 188)


def test_no_upscaling(client):
    assert client.get("/iiif/3/quarters/full/2000,/0/default.jpg").status_code == 400
    # !w,h larger than the region clamps instead of upscaling
    r = client.get("/iiif/3/quarters/0,0,100,100/!500,500/0/default.jpg")
    assert open_image(r).size == (100, 100)


def test_region_outside_or_zero_area(client):
    assert client.get("/iiif/3/quarters/900,0,10,10/max/0/default.jpg").status_code == 400
    assert client.get("/iiif/3/quarters/0,0,0,10/max/0/default.jpg").status_code == 400
    assert client.get("/iiif/3/quarters/pct:200,0,10,10/max/0/default.jpg").status_code == 400


def test_rotation_and_mirror(client):
    r = client.get("/iiif/3/quarters/0,0,100,50/max/90/default.png")
    assert open_image(r).size == (50, 100)  # clockwise 90 swaps dims
    r = client.get("/iiif/3/quarters/0,0,100,50/max/!90/default.png")
    assert open_image(r).size == (50, 100)
    assert client.get("/iiif/3/quarters/full/max/45/default.png").status_code == 400


def test_gray_quality(client):
    r = client.get("/iiif/3/quarters/full/max/0/gray.png")
    assert open_image(r).mode == "L"
    assert client.get("/iiif/3/quarters/full/max/0/bitonal.png").status_code == 400


def test_alpha_composited_on_white_for_jpeg(client):
    r = client.get("/iiif/3/alpha/full/max/0/default.jpg")
    assert r.status_code == 200
    im = open_image(r).convert("RGB")
    assert im.getpixel((5, 5)) == (255, 255, 255)  # transparent corner -> white


def test_bad_numbers_rejected(client):
    assert client.get("/iiif/3/quarters/0,0,-5,10/max/0/default.jpg").status_code == 400
    assert client.get("/iiif/3/quarters/0,0,1e3,10/max/0/default.jpg").status_code == 400
    assert client.get("/iiif/3/quarters/full/abc,/0/default.jpg").status_code == 400
    assert client.get("/iiif/3/quarters/full/max/0/default.gif").status_code == 400


def test_unknown_id_and_path_escape(client):
    assert client.get("/iiif/3/nope/full/max/0/default.jpg").status_code == 404
    escaped = config.BASE_DIR / "escaped.png"
    Image.new("RGB", (10, 10)).save(escaped)
    manifest = json.loads((config.BASE_DIR / "manifest.json").read_text())
    manifest["images"]["evil"] = "../escaped.png"
    (config.BASE_DIR / "manifest.json").write_text(json.dumps(manifest))
    try:
        assert client.get("/iiif/3/evil/full/max/0/default.jpg").status_code == 403
    finally:
        escaped.unlink()
        restore_manifest()


def test_symlink_rejected(client, tmp_path):
    outside = tmp_path / "secret.png"
    Image.new("RGB", (10, 10)).save(outside)
    link = config.IMAGE_ROOT / "link.png"
    link.symlink_to(outside)
    manifest = json.loads((config.BASE_DIR / "manifest.json").read_text())
    manifest["images"]["link"] = "link.png"
    (config.BASE_DIR / "manifest.json").write_text(json.dumps(manifest))
    try:
        assert client.get("/iiif/3/link/full/max/0/default.jpg").status_code == 403
    finally:
        link.unlink()
        restore_manifest()


def test_etag_and_if_none_match(client):
    url = "/iiif/3/quarters/full/max/0/default.jpg"
    r1 = client.get(url)
    etag = r1.headers["ETag"]
    r2 = client.get(url, headers={"If-None-Match": etag})
    assert r2.status_code == 304
    assert r2.content == b""


def test_cache_reuse_and_source_replacement(client):
    url = "/iiif/3/quarters/0,0,50,50/max/0/default.jpg"
    before = cache.stats()["entries"]
    client.get(url)
    mid = cache.stats()["entries"]
    client.get(url)  # equivalent request reuses the entry
    assert cache.stats()["entries"] == mid == before + 1

    # Atomic source replacement -> new version -> fresh derivative.
    target = config.IMAGE_ROOT / "quarters.png"
    original = target.read_bytes()
    tmp = config.IMAGE_ROOT / ".quarters.tmp"
    Image.new("RGB", (640, 480), (1, 2, 3)).save(tmp, "PNG")
    os.replace(tmp, target)
    try:
        r = client.get("/iiif/3/quarters/info.json")
        assert (r.json()["width"], r.json()["height"]) == (640, 480)
        r = client.get(url)
        assert r.status_code == 200
        assert cache.stats()["entries"] == mid + 1  # old entry untouched, new one added
    finally:
        tmp2 = config.IMAGE_ROOT / ".quarters.tmp"
        tmp2.write_bytes(original)
        os.replace(tmp2, target)


def test_corrupt_image_rejected(client):
    bad = config.IMAGE_ROOT / "broken.png"
    bad.write_bytes(b"not a real png")
    manifest = json.loads((config.BASE_DIR / "manifest.json").read_text())
    manifest["images"]["broken"] = "broken.png"
    (config.BASE_DIR / "manifest.json").write_text(json.dumps(manifest))
    try:
        assert client.get("/iiif/3/broken/full/max/0/default.jpg").status_code == 400
    finally:
        bad.unlink()
        restore_manifest()
