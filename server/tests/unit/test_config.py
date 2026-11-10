from pathlib import Path

import pytest

from stock_analyzer.config import Settings


def test_defaults_load_with_no_env():
    s = Settings.from_env({})
    assert s.fr_api_key is None and s.openrouter_api_key is None
    assert s.allow_live is True
    assert s.model_main and s.model_cheap
    assert s.playground_max_tokens > 0
    assert s.toc_match_threshold == 85
    assert s.repeated_line_ratio == 0.30
    assert s.min_business_sections == 10
    assert s.data_dir.name == "data"
    assert s.cache_dir == s.data_dir / "cache"


def test_env_overrides():
    s = Settings.from_env(
        {
            "DATA_DIR": "/tmp/sa-data",
            "ALLOW_LIVE": "false",
            "CORS_ORIGINS": "https://a.example, https://b.example",
            "MODEL_MAIN": "vendor/main",
            "MODEL_CHEAP": "vendor/cheap",
            "PLAYGROUND_MAX_TOKENS": "1234",
            "TOC_MATCH_THRESHOLD": "90",
        }
    )
    assert s.data_dir == Path("/tmp/sa-data")
    assert s.allow_live is False
    assert s.cors_origins == ("https://a.example", "https://b.example")
    assert s.model_for("main") == "vendor/main"
    assert s.model_for("cheap") == "vendor/cheap"
    assert s.playground_max_tokens == 1234
    assert s.toc_match_threshold == 90


def test_bad_values_are_explained():
    with pytest.raises(ValueError, match="ALLOW_LIVE"):
        Settings.from_env({"ALLOW_LIVE": "maybe"})
    with pytest.raises(ValueError, match="PLAYGROUND_MAX_TOKENS"):
        Settings.from_env({"PLAYGROUND_MAX_TOKENS": "lots"})
    with pytest.raises(ValueError, match="unknown model role"):
        Settings.from_env({}).model_for("fancy")


def test_secrets_never_in_repr():
    s = Settings.from_env({"FR_API_KEY": "fr-SECRET-123", "OPENROUTER_API_KEY": "or-SECRET-456"})
    for text in (repr(s), str(s), s.model_dump_json()):
        assert "fr-SECRET-123" not in text
        assert "or-SECRET-456" not in text
    assert s.fr_api_key.get_secret_value() == "fr-SECRET-123"
    assert s.credential_flags() == {"fr_api_key": True, "openrouter_api_key": True}
