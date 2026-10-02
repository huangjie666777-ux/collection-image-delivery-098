"""Bounded on-disk LRU cache for derivative images.

- Cache keys embed the source file version (mtime+size), so an atomic
  replace of a source image yields fresh keys and stale in-flight
  renders can never pollute entries for the new generation.
- Writes go to a temp file followed by os.replace: readers never see
  partial content and failed renders leave nothing behind.
- A per-key asyncio lock makes concurrent equivalent requests render
  exactly once.
"""
import asyncio
import hashlib
import os
import tempfile
from collections import OrderedDict
from pathlib import Path


class DerivativeCache:
    def __init__(self, cache_dir: Path, max_bytes: int):
        self.cache_dir = cache_dir
        self.max_bytes = max_bytes
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._entries: OrderedDict[str, int] = OrderedDict()  # name -> size, LRU order
        self._total = 0
        self._locks: dict[str, asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()
        self._scan()

    def _scan(self) -> None:
        for entry in sorted(self.cache_dir.glob("*.bin"), key=lambda p: p.stat().st_mtime_ns):
            size = entry.stat().st_size
            self._entries[entry.name] = size
            self._total += size
        self._evict()

    def _path(self, name: str) -> Path:
        return self.cache_dir / name

    def _evict(self) -> None:
        while self._total > self.max_bytes and self._entries:
            name, size = self._entries.popitem(last=False)
            try:
                self._path(name).unlink()
            except FileNotFoundError:
                pass
            self._total -= size

    @staticmethod
    def key_for(token: str, version: str) -> str:
        return hashlib.sha256(f"{version}|{token}".encode()).hexdigest()

    def get(self, key: str) -> bytes | None:
        name = key + ".bin"
        if name not in self._entries:
            return None
        try:
            data = self._path(name).read_bytes()
        except FileNotFoundError:
            self._total -= self._entries.pop(name)
            return None
        self._entries.move_to_end(name)
        return data

    def put(self, key: str, data: bytes) -> None:
        name = key + ".bin"
        fd, tmp = tempfile.mkstemp(dir=self.cache_dir, prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            os.replace(tmp, self._path(name))  # atomic publish
        except BaseException:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass
            raise
        old = self._entries.pop(name, 0)
        self._entries[name] = len(data)
        self._total += len(data) - old
        self._evict()

    async def lock_for(self, key: str) -> asyncio.Lock:
        async with self._locks_guard:
            return self._locks.setdefault(key, asyncio.Lock())

    async def release_lock(self, key: str) -> None:
        async with self._locks_guard:
            self._locks.pop(key, None)

