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
    assert s.agent_max_turns == 8
    assert (s.story_reader_role, s.story_writer_role) == ("cheap", "main")
    assert s.story_writer_max_turns == 40
    assert (s.story_max_searches, s.story_search_results, s.story_osint_max_age_days) == (20, 5, 30)


def test_story_web_settings_override_and_change_the_config_hash():
    from stock_analyzer.story.pipeline import _config_hash_from

    base = Settings.from_env({})
    env = {"STORY_MAX_SEARCHES": "7", "STORY_SEARCH_RESULTS": "3", "STORY_OSINT_MAX_AGE_DAYS": "10"}
    s = Settings.from_env(env)
    assert (s.story_max_searches, s.story_search_results, s.story_osint_max_age_days) == (7, 3, 10)
    for name, value in env.items():
        assert _config_hash_from(Settings.from_env({name: value})) != _config_hash_from(base), name
    with pytest.raises(ValueError, match="STORY_MAX_SEARCHES"):
        Settings.from_env({"STORY_MAX_SEARCHES": "lots"})


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
            "AGENT_MAX_TURNS": "12",
            "STORY_READER_ROLE": "main",
            "STORY_WRITER_ROLE": "cheap",
        }
    )
    assert s.agent_max_turns == 12
    assert (s.story_reader_role, s.story_writer_role) == ("main", "cheap")
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
    with pytest.raises(ValueError, match="AGENT_MAX_TURNS"):
        Settings.from_env({"AGENT_MAX_TURNS": "many"})
    with pytest.raises(ValueError, match="story_reader_role"):
        Settings.from_env({"STORY_READER_ROLE": "fancy"})


def test_secrets_never_in_repr():
    s = Settings.from_env({"FR_API_KEY": "fr-SECRET-123", "OPENROUTER_API_KEY": "or-SECRET-456"})
    for text in (repr(s), str(s), s.model_dump_json()):
        assert "fr-SECRET-123" not in text
        assert "or-SECRET-456" not in text
    assert s.fr_api_key.get_secret_value() == "fr-SECRET-123"
    assert s.credential_flags() == {"fr_api_key": True, "openrouter_api_key": True}


def test_database_url_unset_blank_and_set():
    assert Settings.from_env({}).database_url is None
    assert Settings.from_env({"DATABASE_URL": "   "}).database_url is None
    url = "postgresql://postgres.ref:pw-SECRET-789@pooler.example:5432/postgres"
    s = Settings.from_env({"DATABASE_URL": f"  {url} "})
    assert s.database_url.get_secret_value() == url
    for text in (repr(s), str(s), s.model_dump_json()):
        assert "pw-SECRET-789" not in text
        assert "pooler.example" not in text


def test_every_env_var_is_in_env_example():
    import inspect
    import re

    names = set(re.findall(r'"([A-Z][A-Z0-9_]+)"', inspect.getsource(Settings.from_env)))
    example = (Path(__file__).resolve().parents[3] / ".env.example").read_text(encoding="utf-8")
    documented = set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", example, re.M))
    assert "DATABASE_URL" in names
    assert names - documented == set()
    assert re.search(r"^DATABASE_URL=$", example, re.M)  # empty: the file backend by default


def test_osint_settings_defaults_and_overrides():
    s = Settings.from_env({})
    assert s.model_for("osint") == "openai/gpt-6.1-sol"
    assert (s.osint_max_searches, s.osint_search_results, s.osint_max_turns, s.osint_window_months) == (
        40,
        8,
        12,
        36,
    )
    s = Settings.from_env(
        {
            "MODEL_OSINT": "vendor/research",
            "OSINT_MAX_SEARCHES": "5",
            "OSINT_SEARCH_RESULTS": "3",
            "OSINT_MAX_TURNS": "4",
            "OSINT_WINDOW_MONTHS": "6",
        }
    )
    assert s.model_for("osint") == "vendor/research"
    assert s.model_for("main") != "vendor/research"
    assert (s.osint_max_searches, s.osint_search_results, s.osint_max_turns, s.osint_window_months) == (
        5,
        3,
        4,
        6,
    )
