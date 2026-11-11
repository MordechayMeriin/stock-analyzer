"""State store: where the server keeps caches, reports, financials snapshots and usage logs.

``get_store(settings)`` picks the backend from configuration (state-store spec):
Postgres when ``DATABASE_URL`` is set, files under ``DATA_DIR`` otherwise.

- File stores are cheap and created per caller; ``close()`` releases their cache handles.
- Postgres stores share one connection pool per database URL and schema for the whole
  process; their ``close()`` is a no-op (the pool closes at exit, or via ``shutdown_stores``).
"""

from __future__ import annotations

import threading

from stock_analyzer.config import Settings
from stock_analyzer.store.base import KVCache, ReportMeta, Store, StoreLog, fr_totals, llm_totals
from stock_analyzer.store.fs import FsStore

__all__ = [
    "FsStore",
    "KVCache",
    "ReportMeta",
    "Store",
    "StoreLog",
    "fr_totals",
    "get_store",
    "llm_totals",
    "shutdown_stores",
]

DEFAULT_SCHEMA = "stock_analyzer"

_PG_STORES: dict[tuple[str, str], Store] = {}
_PG_GUARD = threading.Lock()


def get_store(settings: Settings, *, schema: str = DEFAULT_SCHEMA) -> Store:
    if settings.database_url is None:
        return FsStore(settings)
    url = settings.database_url.get_secret_value()
    with _PG_GUARD:
        store = _PG_STORES.get((url, schema))
        if store is None:
            from stock_analyzer.store.pg import PgStore

            store = PgStore(url, schema=schema)
            _PG_STORES[(url, schema)] = store
        return store


def shutdown_stores() -> None:
    """Close every shared Postgres pool (tests, and process exit)."""
    with _PG_GUARD:
        stores = list(_PG_STORES.values())
        _PG_STORES.clear()
    for store in stores:
        store.shutdown()  # type: ignore[attr-defined]
