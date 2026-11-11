"""Filesystem backend: today's on-disk layout under ``DATA_DIR`` (design D1).

cache/fr, cache/llm           diskcache (SQLite) key-value caches
raw/<TICKER>/<year>.md        report Markdown, exact bytes (no newline translation)
raw/<TICKER>/<year>.meta.json ReportMeta
raw/<TICKER>/financials[_revisions].json
logs/fr.jsonl, logs/llm.jsonl append-only usage logs
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, Literal

import diskcache

from stock_analyzer.config import Settings
from stock_analyzer.store.base import Namespace, ReportMeta, Source, fr_totals, llm_totals

_LOCKS: dict[Path, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(path: Path) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(path, threading.Lock())


def read_exact(path: Path) -> str:
    """Read UTF-8 text without newline translation (Path.read_text(newline=) needs Python 3.13)."""
    with path.open(encoding="utf-8", newline="") as fh:
        return fh.read()


def raw_paths(settings: Settings, ticker: str, fiscal_year: int) -> tuple[Path, Path]:
    base = settings.raw_dir / ticker.upper()
    return base / f"{fiscal_year}.md", base / f"{fiscal_year}.meta.json"


class JsonlLog:
    """Append-only JSONL log file. The caller supplies complete records."""

    def __init__(self, path: Path):
        self.path = path

    def append(self, record: Mapping[str, Any]) -> None:
        line = json.dumps(dict(record), ensure_ascii=False, default=str)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _lock_for(self.path), self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            yield json.loads(line)


class _DiskCache:
    """diskcache wrapper that opens lazily, so constructing a client never touches disk."""

    def __init__(self, directory: Path):
        self.directory = directory
        self._cache: diskcache.Cache | None = None

    @property
    def _c(self) -> diskcache.Cache:
        if self._cache is None:
            self._cache = diskcache.Cache(str(self.directory))
        return self._cache

    def get(self, key: str) -> Any | None:
        return self._c.get(key)

    def set(self, key: str, value: Any) -> None:
        self._c.set(key, value)

    def delete(self, key: str) -> None:
        self._c.delete(key)

    def __contains__(self, key: object) -> bool:
        return key in self._c

    def close(self) -> None:
        if self._cache is not None:
            self._cache.close()
            self._cache = None


class FsStore:
    backend: Literal["fs"] = "fs"

    def __init__(self, settings: Settings):
        self.settings = settings
        self._caches: dict[str, _DiskCache] = {}

    def cache(self, namespace: Namespace) -> _DiskCache:
        if namespace not in self._caches:
            self._caches[namespace] = _DiskCache(self.settings.cache_dir / namespace)
        return self._caches[namespace]

    # -- reports

    def save_report(self, ticker: str, fiscal_year: int, meta: ReportMeta, text: str) -> None:
        md_path, meta_path = raw_paths(self.settings, ticker, fiscal_year)
        md_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = md_path.with_suffix(".md.tmp")
        tmp.write_text(text, encoding="utf-8", newline="")
        tmp.replace(md_path)
        meta_path.write_text(meta.model_dump_json(indent=2), encoding="utf-8")

    def load_report(self, ticker: str, fiscal_year: int) -> tuple[str, ReportMeta] | None:
        md_path, meta_path = raw_paths(self.settings, ticker, fiscal_year)
        if not (md_path.exists() and meta_path.exists()):
            return None
        meta = ReportMeta.model_validate_json(meta_path.read_text(encoding="utf-8"))
        return read_exact(md_path), meta

    def cached_filing_id(self, ticker: str, fiscal_year: int) -> int | None:
        md_path, meta_path = raw_paths(self.settings, ticker, fiscal_year)
        if not (md_path.exists() and meta_path.exists()):
            return None
        return json.loads(meta_path.read_text(encoding="utf-8")).get("filing_id")

    def report_location(self, ticker: str, fiscal_year: int) -> str:
        return str(raw_paths(self.settings, ticker, fiscal_year)[0])

    def save_financials(self, ticker: str, revisions: bool, data: Any) -> None:
        name = "financials_revisions.json" if revisions else "financials.json"
        path = self.settings.raw_dir / ticker.upper() / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    # -- logs

    def _log_path(self, source: Source) -> Path:
        return self.settings.logs_dir / f"{source}.jsonl"

    def log(self, source: Source, record: Mapping[str, Any]) -> None:
        JsonlLog(self._log_path(source)).append(record)

    def totals(self, source: Source) -> dict[str, Any]:
        records = read_jsonl(self._log_path(source))
        return fr_totals(records) if source == "fr" else llm_totals(records)

    # -- lifecycle

    def ping(self) -> bool:
        """True when the data directory exists (or can be created) and is writable."""
        try:
            self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return False
        return os.access(self.settings.data_dir, os.W_OK)

    def close(self) -> None:
        for cache in self._caches.values():
            cache.close()
