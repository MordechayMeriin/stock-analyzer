"""Postgres backend for the state store (design D3-D5).

- Tables live in one schema (``stock_analyzer`` by default), created by ``schema.sql``
  through ``stock-analyzer db init``; a missing schema raises :class:`StorageNotInitialized`.
- A small in-process pool: up to ``max_size`` connections, opened on demand in the caller's
  thread (so failures surface immediately, with no background reconnect threads logging
  driver messages), reused while healthy, retried once when a reused connection went stale.
- ``prepare_threshold=None`` so transaction-mode poolers (Supavisor port 6543) also work.
- Error messages never include the connection string, host, user or password.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from importlib import resources
from typing import Any, Literal, TypeVar

import psycopg
from psycopg import sql
from psycopg.pq import TransactionStatus
from psycopg.types.json import Jsonb

from stock_analyzer.errors import StorageNotInitialized, StorageUnavailable
from stock_analyzer.store.base import Namespace, ReportMeta, Source

T = TypeVar("T")

DEFAULT_SCHEMA = "stock_analyzer"
INIT_HINT = "run `stock-analyzer db init` with DATABASE_URL set"
_SCHEMA_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def schema_sql(schema: str = DEFAULT_SCHEMA) -> str:
    """The DDL from ``schema.sql``, for ``schema`` (tests use throwaway schemas)."""
    text = resources.files("stock_analyzer.store").joinpath("schema.sql").read_text(encoding="utf-8")
    if schema != DEFAULT_SCHEMA:
        text = re.sub(rf"\b{DEFAULT_SCHEMA}\b", schema, text)
    return text


class _Pool:
    def __init__(self, url: str, *, max_size: int, connect_timeout: int, wait_timeout: float):
        self._url = url
        self._connect_timeout = connect_timeout
        self._wait_timeout = wait_timeout
        self._idle: list[psycopg.Connection] = []
        self._lock = threading.Lock()
        self._slots = threading.BoundedSemaphore(max_size)

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(
            self._url, autocommit=True, prepare_threshold=None, connect_timeout=self._connect_timeout
        )

    @contextmanager
    def connection(self) -> Iterator[tuple[psycopg.Connection, bool]]:
        """Yield ``(connection, reused)``. Broken or mid-transaction connections are discarded."""
        if not self._slots.acquire(timeout=self._wait_timeout):
            raise StorageUnavailable("database busy: no free connection")
        conn: psycopg.Connection | None = None
        try:
            with self._lock:
                while self._idle and conn is None:
                    candidate = self._idle.pop()
                    if candidate.closed or candidate.broken:
                        candidate.close()
                    else:
                        conn = candidate
            reused = conn is not None
            if conn is None:
                conn = self._connect()
            yield conn, reused
        finally:
            if conn is not None:
                healthy = (
                    not conn.closed
                    and not conn.broken
                    and conn.info.transaction_status == TransactionStatus.IDLE
                )
                if healthy:
                    with self._lock:
                        self._idle.append(conn)
                else:
                    conn.close()
            self._slots.release()

    def close(self) -> None:
        with self._lock:
            idle, self._idle = self._idle, []
        for conn in idle:
            conn.close()


class PgStore:
    backend: Literal["postgres"] = "postgres"

    def __init__(
        self,
        url: str,
        *,
        schema: str = DEFAULT_SCHEMA,
        max_size: int = 4,
        connect_timeout: int = 5,
        wait_timeout: float = 10.0,
    ):
        if not _SCHEMA_NAME.match(schema):
            raise ValueError(f"invalid schema name {schema!r}")
        self.schema = schema
        self._pool = _Pool(url, max_size=max_size, connect_timeout=connect_timeout, wait_timeout=wait_timeout)
        self._initialized = False
        s = sql.Identifier(schema)

        def q(text: str) -> sql.Composed:
            return sql.SQL(text).format(s=s)

        self._q = {
            "kv_get": q("select value from {s}.kv_cache where namespace = %s and key = %s"),
            "kv_has": q("select 1 from {s}.kv_cache where namespace = %s and key = %s"),
            "kv_set": q(
                "insert into {s}.kv_cache (namespace, key, value) values (%s, %s, %s) "
                "on conflict (namespace, key) do update set value = excluded.value, updated_at = now()"
            ),
            "kv_del": q("delete from {s}.kv_cache where namespace = %s and key = %s"),
            "report_save": q(
                "insert into {s}.reports (ticker, fiscal_year, filing_id, meta, text, fetched_at) "
                "values (%s, %s, %s, %s, %s, %s) on conflict (ticker, fiscal_year) do update set "
                "filing_id = excluded.filing_id, meta = excluded.meta, text = excluded.text, "
                "fetched_at = excluded.fetched_at"
            ),
            "report_load": q("select text, meta from {s}.reports where ticker = %s and fiscal_year = %s"),
            "report_filing": q("select filing_id from {s}.reports where ticker = %s and fiscal_year = %s"),
            "fin_save": q(
                "insert into {s}.financials_snapshots (ticker, revisions, data) values (%s, %s, %s) "
                "on conflict (ticker, revisions) do update set data = excluded.data, fetched_at = now()"
            ),
            "log": q("insert into {s}.usage_log (source, record) values (%s, %s)"),
            # same semantics as store.base.fr_totals / llm_totals
            "totals_fr": q(
                "select count(*), count(*) filter (where record->>'cache' = 'hit'), "
                "coalesce(sum(coalesce((record->>'credits')::bigint, 0)), 0) "
                "from {s}.usage_log where source = 'fr'"
            ),
            "totals_llm": q(
                "select count(*), "
                "count(*) filter (where coalesce((record->>'cache_hit')::boolean, false)), "
                "count(*) filter (where record ? 'ok' and record->'ok' in ('false'::jsonb, 'null'::jsonb)), "
                "coalesce(sum(coalesce((record->>'cost')::float8, 0)), 0) "
                "from {s}.usage_log where source = 'llm'"
            ),
        }

    def __repr__(self) -> str:  # never show the URL
        return f"PgStore(schema={self.schema!r})"

    # -- plumbing

    def _run(self, fn: Callable[[psycopg.Connection], T], *, check_schema: bool = True) -> T:
        for attempt in (1, 2):
            try:
                with self._pool.connection() as (conn, reused):
                    try:
                        if check_schema and not self._initialized:
                            self._check_schema(conn)
                        return fn(conn)
                    except psycopg.OperationalError:
                        if reused and attempt == 1:
                            conn.close()  # stale pooled connection: retry once on a fresh one
                            raise _Retry from None
                        raise
            except _Retry:
                continue
            except psycopg.errors.UndefinedTable:
                self._initialized = False
                raise StorageNotInitialized(
                    f"the database schema {self.schema!r} is missing; {INIT_HINT}"
                ) from None
            except psycopg.OperationalError as exc:
                raise StorageUnavailable(f"database unreachable ({type(exc).__name__})") from None
        raise AssertionError("unreachable")  # pragma: no cover

    def _check_schema(self, conn: psycopg.Connection) -> None:
        row = conn.execute("select to_regclass(%s)", (f"{self.schema}.kv_cache",)).fetchone()
        if row is None or row[0] is None:
            raise StorageNotInitialized(f"the database schema {self.schema!r} is missing; {INIT_HINT}")
        self._initialized = True

    def _one(self, query: str, params: tuple[Any, ...]) -> tuple[Any, ...] | None:
        return self._run(lambda c: c.execute(self._q[query], params).fetchone())

    def _exec(self, query: str, params: tuple[Any, ...]) -> None:
        self._run(lambda c: c.execute(self._q[query], params))

    # -- cache

    def cache(self, namespace: Namespace) -> _PgCache:
        return _PgCache(self, namespace)

    # -- reports

    def save_report(self, ticker: str, fiscal_year: int, meta: ReportMeta, text: str) -> None:
        self._exec(
            "report_save",
            (ticker, fiscal_year, meta.filing_id, Jsonb(meta.model_dump(mode="json")), text, meta.fetched_at),
        )

    def load_report(self, ticker: str, fiscal_year: int) -> tuple[str, ReportMeta] | None:
        row = self._one("report_load", (ticker, fiscal_year))
        if row is None:
            return None
        return row[0], ReportMeta.model_validate(row[1])

    def cached_filing_id(self, ticker: str, fiscal_year: int) -> int | None:
        row = self._one("report_filing", (ticker, fiscal_year))
        return int(row[0]) if row else None

    def report_location(self, ticker: str, fiscal_year: int) -> str:
        return f"postgres:{self.schema}.reports/{ticker.upper()}/{fiscal_year}"

    def save_financials(self, ticker: str, revisions: bool, data: Any) -> None:
        self._exec("fin_save", (ticker, revisions, Jsonb(data)))

    # -- logs

    def log(self, source: Source, record: Mapping[str, Any]) -> None:
        self._exec("log", (source, Jsonb(dict(record), dumps=_dumps)))

    def totals(self, source: Source) -> dict[str, Any]:
        if source == "fr":
            calls, hits, credits = self._one("totals_fr", ())
            return {
                "calls": calls,
                "cache_hits": hits,
                "network_calls": calls - hits,
                "credits_logged": int(credits),
            }
        calls, hits, failures, cost = self._one("totals_llm", ())
        return {
            "calls": calls,
            "cache_hits": hits,
            "failures": failures,
            "total_cost_usd": round(float(cost), 6),
        }

    # -- schema and lifecycle

    def init_schema(self) -> bool:
        """Apply ``schema.sql``. Returns True when the schema already existed."""

        def apply(conn: psycopg.Connection) -> bool:
            row = conn.execute("select to_regclass(%s)", (f"{self.schema}.kv_cache",)).fetchone()
            existed = bool(row and row[0])
            with conn.transaction():
                conn.execute(schema_sql(self.schema).encode("utf-8"))
            return existed

        existed = self._run(apply, check_schema=False)
        self._initialized = True
        return existed

    def ping(self) -> bool:
        """True when the database answers and the schema exists."""
        try:
            self._run(lambda c: c.execute("select 1").fetchone())
        except (StorageUnavailable, StorageNotInitialized):
            return False
        return True

    def close(self) -> None:
        """No-op: the pool is shared by every user of this store (see ``shutdown``)."""

    def shutdown(self) -> None:
        self._pool.close()


class _Retry(Exception):
    pass


def _dumps(obj: Any) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False, default=str)


class _PgCache:
    def __init__(self, store: PgStore, namespace: Namespace):
        self._store = store
        self._ns = namespace

    def get(self, key: str) -> Any | None:
        row = self._store._one("kv_get", (self._ns, key))
        return row[0] if row else None

    def set(self, key: str, value: Any) -> None:
        self._store._exec("kv_set", (self._ns, key, Jsonb(value)))

    def delete(self, key: str) -> None:
        self._store._exec("kv_del", (self._ns, key))

    def __contains__(self, key: object) -> bool:
        return self._store._one("kv_has", (self._ns, key)) is not None

    def close(self) -> None:
        pass
