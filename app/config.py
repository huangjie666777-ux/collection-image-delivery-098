"""Central configuration for the IIIF image service."""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Only files under this directory may ever be served.
IMAGE_ROOT = BASE_DIR / "images"

# JSON manifest mapping image IDs to root-relative paths.
MANIFEST_PATH = BASE_DIR / "manifest.json"

# Disk cache for derived images.
CACHE_DIR = BASE_DIR / ".cache" / "derivatives"
CACHE_MAX_BYTES = 64 * 1024 * 1024  # 64 MiB LRU capacity

# Safety limits.
MAX_DECODE_PIXELS = 100_000_000  # reject decompression bombs
MAX_PARALLEL_TRANSFORMS = 2  # bound concurrent CPU-heavy image work
