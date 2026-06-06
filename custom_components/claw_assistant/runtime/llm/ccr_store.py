from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import logging
import os
from pathlib import Path
import queue
import re
import threading
import time

LOGGER = logging.getLogger(__name__)

_MAX_ENTRIES = 500
_MAX_TOTAL_BYTES = 32 * 1024 * 1024
_MIN_STORE_LEN = 200

_DISK_MAX_FILES = 2000
_DISK_MAX_BYTES = 256 * 1024 * 1024
_DISK_TTL_SECONDS = 7 * 24 * 3600
_CLEANUP_EVERY_WRITES = 64

_ID_RE = re.compile(r"^[0-9a-f]{1,16}$")


@dataclass(slots=True)
class _Entry:
    content: str
    tool_name: str
    size: int


class CCRStore:

    def __init__(
        self,
        *,
        max_entries: int = _MAX_ENTRIES,
        max_total_bytes: int = _MAX_TOTAL_BYTES,
        persist_dir: Path | None = None,
        disk_max_files: int = _DISK_MAX_FILES,
        disk_max_bytes: int = _DISK_MAX_BYTES,
        disk_ttl_seconds: int = _DISK_TTL_SECONDS,
    ) -> None:
        self._max_entries = max_entries
        self._max_total_bytes = max_total_bytes
        self._lock = threading.Lock()
        self._entries: "OrderedDict[str, _Entry]" = OrderedDict()
        self._total_bytes = 0

        self._persist_dir: Path | None = None
        self._disk_max_files = disk_max_files
        self._disk_max_bytes = disk_max_bytes
        self._disk_ttl_seconds = disk_ttl_seconds
        self._write_q: "queue.Queue[tuple[str, str] | None] | None" = None
        self._writes_since_cleanup = 0
        if persist_dir is not None:
            self._init_persistence(persist_dir)

    # ------------------------------------------------------------------ core

    @staticmethod
    def _make_id(content: str) -> str:
        return hashlib.sha1(content.encode("utf-8", "replace")).hexdigest()[:10]

    def put(self, content: object, *, tool_name: str = "") -> str | None:
        if not content:
            return None
        text = content if isinstance(content, str) else str(content)
        if len(text) < _MIN_STORE_LEN:
            return None
        cid = self._make_id(text)
        size = len(text.encode("utf-8", "replace"))
        with self._lock:
            existing = self._entries.get(cid)
            if existing is not None:
                self._entries.move_to_end(cid)
            else:
                self._entries[cid] = _Entry(content=text, tool_name=tool_name, size=size)
                self._total_bytes += size
                self._evict_locked()
        self._enqueue_write(cid, text)
        return cid

    def get(self, cid: str) -> str | None:
        if not cid:
            return None
        with self._lock:
            entry = self._entries.get(cid)
            if entry is not None:
                self._entries.move_to_end(cid)
                return entry.content
        # Memory miss — fall back to disk (survives restarts).
        return self._read_disk(cid)

    def info(self, cid: str) -> dict[str, object] | None:
        with self._lock:
            entry = self._entries.get(cid)
            if entry is None:
                return None
            return {"id": cid, "tool_name": entry.tool_name, "size": entry.size}

    def stats(self) -> dict[str, int | bool]:
        with self._lock:
            return {
                "entries": len(self._entries),
                "total_bytes": self._total_bytes,
                "persistent": self._persist_dir is not None,
            }

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._total_bytes = 0

    def _evict_locked(self) -> None:
        while self._entries and (
            len(self._entries) > self._max_entries
            or self._total_bytes > self._max_total_bytes
        ):
            _cid, evicted = self._entries.popitem(last=False)
            self._total_bytes -= evicted.size

    # ----------------------------------------------------------- persistence

    def _init_persistence(self, persist_dir: Path) -> None:
        try:
            persist_dir.mkdir(parents=True, exist_ok=True)
        except OSError as err:
            LOGGER.warning("CCR persistence disabled (cannot create %s): %s", persist_dir, err)
            return
        self._persist_dir = persist_dir
        self._write_q = queue.Queue(maxsize=1000)
        worker = threading.Thread(
            target=self._writer_loop, name="claw-ccr-writer", daemon=True
        )
        worker.start()

    def _path_for(self, cid: str) -> Path | None:
        if self._persist_dir is None or not _ID_RE.match(cid):
            return None
        return self._persist_dir / f"{cid}.txt"

    def _enqueue_write(self, cid: str, text: str) -> None:
        q = self._write_q
        if q is None:
            return
        try:
            q.put_nowait((cid, text))
        except queue.Full:
            # Persistence is best-effort; memory still holds the original.
            LOGGER.debug("CCR write queue full; skipping disk persist for %s", cid)

    def _writer_loop(self) -> None:
        # Reclaim stale/over-budget files once at startup, off the event loop.
        self._cleanup_disk()
        q = self._write_q
        assert q is not None
        while True:
            item = q.get()
            try:
                if item is None:
                    return
                cid, text = item
                self._write_file(cid, text)
                self._writes_since_cleanup += 1
                if self._writes_since_cleanup >= _CLEANUP_EVERY_WRITES:
                    self._writes_since_cleanup = 0
                    self._cleanup_disk()
            except Exception as err:  # never let the worker die
                LOGGER.debug("CCR writer error: %s", err)
            finally:
                q.task_done()

    def _write_file(self, cid: str, text: str) -> None:
        path = self._path_for(cid)
        if path is None or path.exists():
            return
        tmp = path.with_suffix(".txt.tmp")
        try:
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, path)
        except OSError as err:
            LOGGER.debug("CCR write failed for %s: %s", cid, err)
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass

    def _read_disk(self, cid: str) -> str | None:
        path = self._path_for(cid)
        if path is None or not path.exists():
            return None
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as err:
            LOGGER.debug("CCR read failed for %s: %s", cid, err)
            return None
        try:
            os.utime(path, None)
        except OSError:
            pass
        with self._lock:
            if cid not in self._entries:
                size = len(text.encode("utf-8", "replace"))
                self._entries[cid] = _Entry(content=text, tool_name="", size=size)
                self._total_bytes += size
                self._evict_locked()
        return text

    def _cleanup_disk(self) -> None:
        if self._persist_dir is None:
            return
        try:
            files = list(self._persist_dir.glob("*.txt"))
        except OSError:
            return
        now = time.time()
        stats: list[tuple[float, int, Path]] = []
        for path in files:
            try:
                st = path.stat()
            except OSError:
                continue
            # TTL: drop originals not touched within the retention window.
            if now - st.st_mtime > self._disk_ttl_seconds:
                self._safe_unlink(path)
                continue
            stats.append((st.st_mtime, st.st_size, path))

        total_bytes = sum(size for _mtime, size, _p in stats)
        if len(stats) <= self._disk_max_files and total_bytes <= self._disk_max_bytes:
            return
        # Evict oldest-first until both caps are satisfied.
        stats.sort(key=lambda item: item[0])
        count = len(stats)
        for _mtime, size, path in stats:
            if count <= self._disk_max_files and total_bytes <= self._disk_max_bytes:
                break
            if self._safe_unlink(path):
                count -= 1
                total_bytes -= size

    @staticmethod
    def _safe_unlink(path: Path) -> bool:
        try:
            path.unlink(missing_ok=True)
            return True
        except OSError:
            return False


_store: CCRStore | None = None
_store_lock = threading.Lock()


def _persistence_enabled() -> bool:
    flag = os.environ.get("CLAW_CCR_PERSIST", "1").strip().lower()
    return flag not in ("0", "false", "no", "off")


def _default_persist_dir() -> Path | None:
    if not _persistence_enabled():
        return None
    try:
        from ..utils.data_path import get_data_dir

        return get_data_dir() / "runtime" / "ccr"
    except Exception as err:  # pragma: no cover - defensive
        LOGGER.debug("CCR persist dir unavailable, using memory only: %s", err)
        return None


def get_ccr_store() -> CCRStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = CCRStore(persist_dir=_default_persist_dir())
    return _store
