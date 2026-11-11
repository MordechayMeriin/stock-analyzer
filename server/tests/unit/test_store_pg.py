"""Postgres-only state store behaviour: schema setup, failures, sharing (state-store spec).

Runs only when ``TEST_DATABASE_URL`` is set (see ``conftest.py``).
"""

from __future__ import annotations

import time
import uuid

import psycopg
import pytest

from stock_analyzer.errors import StorageNotInitialized, StorageUnavailable
from stock_analyzer.store.pg import PgStore
from tests.conftest import TEST_DATABASE_URL

pytestmark = pytest.mark.skipif(TEST_DATABASE_URL is None, reason="TEST_DATABASE_URL not set")


@pytest.fixture
def bare_schema():
    """A schema name with nothing created yet; dropped afterwards if anything was."""
    name = f"sa_test_{uuid.uuid4().hex[:12]}"
    yield name
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        conn.execute(f'drop schema if exists "{name}" cascade')


def test_missing_schema_names_the_setup_command(bare_schema):
    store = PgStore(TEST_DATABASE_URL, schema=bare_schema)
    with pytest.raises(StorageNotInitialized) as err:
        store.cache("fr").get("k")
    assert "stock-analyzer db init" in err.value.message
    assert store.ping() is False
    store.shutdown()


def test_init_schema_is_idempotent_and_keeps_data(bare_schema):
    store = PgStore(TEST_DATABASE_URL, schema=bare_schema)
    assert store.init_schema() is False  # created now
    store.cache("llm").set("k", "kept")
    assert store.init_schema() is True  # already there
    assert store.cache("llm").get("k") == "kept"
    assert store.ping() is True
    store.shutdown()


def test_unreachable_database_error_has_no_connection_details():
    url = "postgresql://secret_user:secret_pw@127.0.0.1:1/secret_db"
    store = PgStore(url, connect_timeout=2)
    started = time.monotonic()
    with pytest.raises(StorageUnavailable) as err:
        store.load_report("MLTM", 2025)
    for leak in ("secret_user", "secret_pw", "secret_db", "127.0.0.1", ":1"):
        assert leak not in err.value.message
        assert leak not in str(err.value)
    assert err.value.__cause__ is None and err.value.__suppress_context__
    assert store.ping() is False
    assert time.monotonic() - started < 10  # fails fast, no long pool wait
    assert url not in repr(store)


def test_stale_pooled_connection_is_retried(pg_schema):
    pg_schema.cache("fr").set("k", {"v": 1})
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as admin:
        admin.execute(
            "select pg_terminate_backend(pid) from pg_stat_activity "
            "where datname = current_database() and pid <> pg_backend_pid() and state = 'idle'"
        )
    time.sleep(0.2)
    assert pg_schema.cache("fr").get("k") == {"v": 1}  # reconnects instead of failing


def test_two_store_instances_share_state(pg_schema):
    # e.g. the CLI on a laptop and the API server on the host, same DATABASE_URL
    other = PgStore(TEST_DATABASE_URL, schema=pg_schema.schema)
    pg_schema.log("fr", {"cache": "miss", "credits": 6})
    other.cache("fr").set("k", {"from": "cli"})
    assert pg_schema.cache("fr").get("k") == {"from": "cli"}
    assert other.totals("fr")["credits_logged"] == 6
    other.shutdown()
