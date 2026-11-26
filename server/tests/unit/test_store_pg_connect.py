"""Postgres store: refused connections are retried (no database needed)."""

import pytest


def test_refused_connections_are_retried(monkeypatch):
    """Supabase's session pooler refuses clients past its limit; a new connection is retried."""
    import psycopg

    from stock_analyzer.store import pg

    attempts = []
    sentinel = object()

    def flaky_connect(*args, **kwargs):
        attempts.append(1)
        if len(attempts) < 3:
            raise psycopg.OperationalError("FATAL: (EMAXCONNSESSION) max clients reached in session mode")
        return sentinel

    monkeypatch.setattr(pg.psycopg, "connect", flaky_connect)
    monkeypatch.setattr(pg, "CONNECT_RETRY_DELAYS", (0.0, 0.0))
    pool = pg._Pool("postgresql://u:p@h/db", max_size=1, connect_timeout=1, wait_timeout=1)
    assert pool._connect() is sentinel and len(attempts) == 3

    # an unreachable server is not retried: it must fail fast
    def down(*args, **kwargs):
        attempts.append(1)
        raise psycopg.OperationalError("connection refused")

    attempts.clear()
    monkeypatch.setattr(pg.psycopg, "connect", down)
    with pytest.raises(psycopg.OperationalError):
        pool._connect()
    assert len(attempts) == 1

    # a server that stays full gives up after the retries
    def full(*args, **kwargs):
        attempts.append(1)
        raise psycopg.OperationalError("FATAL: too many clients already")

    attempts.clear()
    monkeypatch.setattr(pg.psycopg, "connect", full)
    with pytest.raises(psycopg.OperationalError):
        pool._connect()
    assert len(attempts) == 3
