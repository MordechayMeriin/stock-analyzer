from pydantic import SecretStr

from stock_analyzer.config import Settings
from stock_analyzer.store import FsStore, get_store


def test_get_store_defaults_to_files(settings):
    store = get_store(settings)
    assert isinstance(store, FsStore) and store.backend == "fs"


def test_get_store_from_env_without_database_url(tmp_path):
    store = get_store(Settings.from_env({"DATA_DIR": str(tmp_path)}))
    assert isinstance(store, FsStore)
    assert store.settings.data_dir == tmp_path


def test_database_url_selects_postgres_without_connecting(settings):
    # constructing the store opens no connection (sockets are blocked in tests)
    store = get_store(
        settings.model_copy(update={"database_url": SecretStr("postgresql://u:p@203.0.113.9/db")})
    )
    assert store.backend == "postgres"
    assert "p@203" not in repr(store)
