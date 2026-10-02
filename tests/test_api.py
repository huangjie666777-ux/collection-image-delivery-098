import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("CACHE_DIR", str(Path(__file__).resolve().parent / ".test-cache"))

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_info():
    r = client.get("/iiif/3/photo/info.json")
    assert r.status_code == 200
    body = r.json()
    assert (body["width"], body["height"]) == (1200, 800)
    assert body["type"] == "ImageService3"


def test_full_max_jpg():
    r = client.get("/iiif/3/photo/full/max/0/default.jpg")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"


def test_region_and_size():
    from PIL import Image
    import io
    r = client.get("/iiif/3/photo/100,100,400,300/!200,200/0/default.png")
    assert r.status_code == 200
    assert Image.open(io.BytesIO(r.content)).size == (200, 150)


def test_region_clamped_to_edges():
    from PIL import Image
    import io
    r = client.get("/iiif/3/photo/1100,700,500,500/max/0/default.png")
    assert r.status_code == 200
    assert Image.open(io.BytesIO(r.content)).size == (100, 100)


def test_region_fully_outside_is_400():
    assert client.get("/iiif/3/photo/5000,0,10,10/max/0/default.jpg").status_code == 400
    assert client.get("/iiif/3/photo/0,0,0,10/max/0/default.jpg").status_code == 400


def test_pct_region_and_rotation():
    from PIL import Image
    import io
    r = client.get("/iiif/3/photo/pct:0,0,50,50/max/90/default.png")
    assert r.status_code == 200
    assert Image.open(io.BytesIO(r.content)).size == (400, 600)


def test_no_upscale():
    from PIL import Image
    import io
    r = client.get("/iiif/3/photo/full/5000,/0/default.png")
    assert Image.open(io.BytesIO(r.content)).size == (1200, 800)


def test_bad_params():
    assert client.get("/iiif/3/photo/full/10/0/default.jpg").status_code == 400
    assert client.get("/iiif/3/photo/full/,/0/default.jpg").status_code == 400
    assert client.get("/iiif/3/photo/full/max/45/default.jpg").status_code == 400
    assert client.get("/iiif/3/photo/full/max/0/bitonal.jpg").status_code == 400
    assert client.get("/iiif/3/photo/full/max/0/default.gif").status_code == 400


def test_unknown_id_and_traversal():
    assert client.get("/iiif/3/nope/info.json").status_code == 404
    assert client.get("/iiif/3/..%2Fsecret/info.json").status_code == 404


def test_etag_304():
    url = "/iiif/3/photo/full/,100/0/default.jpg"
    r1 = client.get(url)
    etag = r1.headers["etag"]
    r2 = client.get(url, headers={"If-None-Match": etag})
    assert r2.status_code == 304 and not r2.content


def test_cache_reuse_and_source_replace():
    url = "/iiif/3/overlay/full/,50/0/default.jpg"  # RGBA -> white bg JPEG
    a = client.get(url)
    b = client.get(url)
    assert a.content == b.content
    # atomic replace of the source must invalidate derivatives
    from PIL import Image
    import tempfile
    img_dir = Path(__file__).resolve().parent.parent / "data" / "images"
    fd, tmp = tempfile.mkstemp(dir=img_dir, suffix=".png")
    os.close(fd)
    Image.new("RGBA", (600, 900), (0, 255, 0, 255)).save(tmp)
    os.replace(tmp, img_dir / "overlay.png")
    try:
        c = client.get(url)
        assert c.status_code == 200 and c.content != a.content
    finally:
        import subprocess
        subprocess.run([sys.executable, "scripts/make_samples.py"], cwd=Path(__file__).resolve().parent.parent, check=True)
