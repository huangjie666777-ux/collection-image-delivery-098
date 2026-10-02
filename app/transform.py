"""Image decoding and the transform pipeline.

Order of operations: crop -> scale -> mirror -> rotate (clockwise) -> gray.
EXIF orientation is applied first; all coordinates refer to the
oriented image.
"""
import io

from PIL import Image, ImageOps

from .iiif import BadRequest, ImageRequest

Image.MAX_IMAGE_PIXELS = None  # we enforce our own explicit limit


class UnprocessableImage(Exception):
    pass


class TooManyPixels(Exception):
    pass


def load_oriented(path, max_pixels: int) -> Image.Image:
    try:
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im)
            if im.width * im.height > max_pixels:
                raise TooManyPixels(f"{im.width}x{im.height} exceeds {max_pixels} pixels")
            im.load()
            return im.copy()
    except TooManyPixels:
        raise
    except Exception as exc:
        raise UnprocessableImage(f"cannot decode image: {exc}") from exc


def apply_request(im: Image.Image, req: ImageRequest) -> Image.Image:
    x, y, w, h = req.region.to_pixels(im.width, im.height)
    im = im.crop((x, y, x + w, y + h))

    tw, th = req.size.target(im.width, im.height)
    if (tw, th) != im.size:
        im = im.resize((tw, th), Image.LANCZOS)

    if req.rotation.mirror:
        im = ImageOps.mirror(im)
    if req.rotation.degrees:
        # PIL rotate is counter-clockwise; IIIF rotation is clockwise.
        im = im.transpose({90: Image.ROTATE_270, 180: Image.ROTATE_180, 270: Image.ROTATE_90}[req.rotation.degrees])

    if req.gray:
        im = ImageOps.grayscale(im)
    return im


def encode(im: Image.Image, fmt: str) -> bytes:
    buf = io.BytesIO()
    if fmt == "jpg":
        if im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info):
            rgba = im.convert("RGBA")
            background = Image.new("RGB", rgba.size, (255, 255, 255))
            background.paste(rgba, mask=rgba.getchannel("A"))
            im = background
        elif im.mode != "RGB":
            im = im.convert("RGB")
        im.save(buf, "JPEG", quality=90)
    else:
        im.save(buf, "PNG")
    return buf.getvalue()


def render(path, req: ImageRequest, max_pixels: int) -> bytes:
    im = load_oriented(path, max_pixels)
    return encode(apply_request(im, req), req.fmt)

