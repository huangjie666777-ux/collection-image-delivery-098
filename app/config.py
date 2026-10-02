import os
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    image_root: Path = Path(os.environ.get("IMAGE_ROOT", BASE_DIR / "data" / "images"))
    manifest_path: Path = Path(os.environ.get("MANIFEST_PATH", BASE_DIR / "data" / "manifest.json"))
    cache_dir: Path = Path(os.environ.get("CACHE_DIR", BASE_DIR / ".cache" / "derivatives"))
    cache_max_bytes: int = int(os.environ.get("CACHE_MAX_BYTES", 256 * 1024 * 1024))
    max_pixels: int = int(os.environ.get("MAX_PIXELS", 100_000_000))
    max_parallel: int = int(os.environ.get("MAX_PARALLEL", 4))


settings = Settings()

