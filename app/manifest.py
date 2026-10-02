"""Manifest loading and safe resolution of source images.

Only PNG/JPEG files that physically live inside the image root are served.
Relative paths that escape the root (via '..' or symlinks) are rejected.
"""
import json
from dataclasses import dataclass
from pathlib import Path

ALLOWED_SUFFIXES = {".png", ".jpg", ".jpeg"}


class ManifestError(Exception):
    pass


class NotFoundError(Exception):
    pass


@dataclass(frozen=True)
class SourceImage:
    image_id: str
    path: Path
    mtime_ns: int
    size: int

    @property
    def version(self) -> str:
        # Changes on atomic replace (new mtime/size), so caches keyed on it
        # never mix bytes from different generations of the same file.
        return f"{self.mtime_ns:x}-{self.size:x}"


class ImageRepository:
    def __init__(self, image_root: Path, manifest_path: Path):
        self.image_root = image_root.resolve()
        self.manifest_path = manifest_path
        self._entries = self._load_manifest()

    def _load_manifest(self) -> dict:
        try:
            data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ManifestError(f"cannot read manifest: {exc}") from exc
        items = data.get("images", data) if isinstance(data, dict) else data
        entries = {}
        for item in items:
            image_id = str(item["id"])
            rel = str(item["path"])
            if "://" in rel or rel.startswith(("/", "\\")):
                raise ManifestError(f"{image_id}: remote or absolute path not allowed")
            entries[image_id] = rel
        return entries

    def resolve(self, image_id: str) -> SourceImage:
        rel = self._entries.get(image_id)
        if rel is None:
            raise NotFoundError(image_id)
        candidate = self.image_root / rel
        try:
            # resolve() follows symlinks; anything escaping the root is rejected.
            real = candidate.resolve(strict=True)
        except (OSError, RuntimeError):
            raise NotFoundError(image_id)
        if not real.is_relative_to(self.image_root):
            raise NotFoundError(image_id)
        if real.suffix.lower() not in ALLOWED_SUFFIXES or not real.is_file():
            raise NotFoundError(image_id)
        st = real.stat()
        return SourceImage(image_id=image_id, path=real, mtime_ns=st.st_mtime_ns, size=st.st_size)

