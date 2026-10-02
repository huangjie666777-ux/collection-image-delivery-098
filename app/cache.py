"""Capacity-bounded disk LRU cache for derived images.

- Equivalent requests share one entry (keyed by a canonical request hash that
  includes the source version, so replaced sources never collide with stale
  entries, and old in-flight results land under the old key).
- Concurrent requests for the same key generate exactly once (single-flight).
- Entries are written to a temp file and atomically renamed; failures leave
  no partial files and can be retried by a later request.
"""

from __future__ import annotations

import os
import tempfile
import threading
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Callable


class DiskLRUCache:
    def __init__(self, directory: Path, max_bytes: int):
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._max_bytes = max_bytes
        self._lock = threading.Lock()
        self._entries: OrderedDict[str, tuple[Path, int]] = OrderedDict()
        self._total = 0
        self._inflight: dict[str, threading.Event] = {}
        self._load_existing()

    def _load_existing(self) -> None:
        files = [p for p in self._dir.iterdir() if p.is_file() and not p.name.endswith(".tmp")]
        files.sort(key=lambda p: p.stat().st_mtime_ns)
        for p in files:
            size = p.stat().st_size
            self._entries[p.stem] = (p, size)
            self._total += size
        self._evict_locked()

    def _evict_locked(self) -> None:
        while self._total > self._max_bytes and self._entries:
            _, (path, size) = self._entries.popitem(last=False)
            self._total -= size
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    def _path_for(self, key: str, ext: str) -> Path:
        return self._dir / f"{key}.{ext}"

    def get_or_create(self, key: str, ext: str, factory: Callable[[], bytes]) -> bytes:
        """Return cached bytes for key, generating once if missing."""
        while True:
            with self._lock:
                entry = self._entries.get(key)
                if entry is not None:
                    self._entries.move_to_end(key)
                    path = entry[0]
                else:
                    path = None
                if path is None:
                    event = self._inflight.get(key)
                    if event is None:
                        event = threading.Event()
                        self._inflight[key] = event
                        creator = True
                    else:
                        creator = False
            if path is not None:
                try:
                    return path.read_bytes()
                except FileNotFoundError:
                    continue  # evicted between lookup and read; retry
            if not creator:
                event.wait()
                continue  # creator finished (success or failure); retry lookup
            try:
                data = factory()
                self._commit(key, ext, data)
                return data
            finally:
                with self._lock:
                    self._inflight.pop(key, None)
                    event.set()

    def _commit(self, key: str, ext: str, data: bytes) -> None:
        fd, tmp_name = tempfile.mkstemp(dir=self._dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            final = self._path_for(key, ext)
            os.replace(tmp_name, final)  # atomic; no half-written entries
        except BaseException:
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass
            raise
        with self._lock:
            old = self._entries.pop(key, None)
            if old is not None:
                self._total -= old[1]
                try:
                    old[0].unlink()
                except FileNotFoundError:
                    pass
            self._entries[key] = (final, len(data))
            self._total += len(data)
            self._evict_locked()

    def clear(self) -> None:
        with self._lock:
            for path, _ in self._entries.values():
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
            self._entries.clear()
            self._total = 0

    def stats(self) -> dict:
        with self._lock:
            return {"entries": len(self._entries), "bytes": self._total}
