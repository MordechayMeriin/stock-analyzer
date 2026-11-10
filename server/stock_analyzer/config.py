"""All runtime settings and thresholds, read from environment variables with defaults.

Rules (plan.md §0, design D6/D9):
- Secrets come from env only and never appear in ``repr()``/``str()``/logs (``SecretStr``).
- Every threshold the parsers and clients use lives here, so nothing is hard-coded elsewhere.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, SecretStr

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off", ""}

SERVER_ROOT = Path(__file__).resolve().parent.parent


def _parse_bool(name: str, raw: str) -> bool:
    value = raw.strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise ValueError(f"{name} must be a boolean (true/false), got {raw!r}")


class Settings(BaseModel):
    """Typed settings. Build with :meth:`from_env`; tests may construct directly."""

    model_config = ConfigDict(frozen=True)

    # --- credentials (env only, never logged) ---
    fr_api_key: SecretStr | None = None
    openrouter_api_key: SecretStr | None = None

    # --- storage / deployment ---
    data_dir: Path = SERVER_ROOT / "data"
    companies_file: Path = SERVER_ROOT / "data" / "companies.yaml"
    prompts_dir: Path = SERVER_ROOT / "prompts"
    allow_live: bool = True
    cors_origins: tuple[str, ...] = ("http://localhost:5173", "http://127.0.0.1:5173")

    # --- FinancialFilings provider ---
    fr_base_url: str = "https://api.financialreports.eu"
    fr_timeout_s: float = 60.0
    fr_max_attempts: int = 5
    fr_backoff_base_s: float = 1.0
    fr_backoff_max_s: float = 60.0
    fr_markdown_page_chars: int = 200_000  # provider maximum per windowed call
    fr_country: str = "IL"

    # --- LLM gateway (OpenRouter) ---
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    model_main: str = "anthropic/claude-sonnet-5.5"
    model_cheap: str = "anthropic/claude-haiku-5.5"
    llm_fake: bool = False  # serve every LLM call from FakeLLM (offline demos and tests)
    llm_timeout_s: float = 120.0
    llm_max_tokens: int = 4096
    playground_max_tokens: int = 60_000  # budget for the selected report text

    # --- report parsing thresholds (plan.md §1.4–1.5) ---
    toc_match_threshold: int = 85  # rapidfuzz token_set_ratio for TOC title anchoring
    chapter_match_threshold: int = 85
    repeated_line_ratio: float = 0.30  # lines on more than this share of pages are stripped
    repeated_line_min_pages: int = 4  # never strip "repeats" in very short documents
    min_business_sections: int = 10
    glued_title_max_chars: int = 120
    chars_per_token: float = 3.0  # conservative estimate for Hebrew text

    # --- financial data ---
    fin_max_years: int = 5

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    def model_for(self, role: str) -> str:
        """Resolve a model *role* (``main`` / ``cheap``) to a configured model id."""
        if role == "main":
            return self.model_main
        if role == "cheap":
            return self.model_cheap
        raise ValueError(f"unknown model role {role!r}; expected 'main' or 'cheap'")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env
        values: dict[str, object] = {}

        def get(name: str) -> str | None:
            raw = env.get(name)
            return raw if raw is not None and raw.strip() != "" else None

        for name, field in (("FR_API_KEY", "fr_api_key"), ("OPENROUTER_API_KEY", "openrouter_api_key")):
            if (raw := get(name)) is not None:
                values[field] = SecretStr(raw.strip())

        if (raw := get("DATA_DIR")) is not None:
            values["data_dir"] = Path(raw).expanduser()
        if (raw := get("COMPANIES_FILE")) is not None:
            values["companies_file"] = Path(raw).expanduser()
        if (raw := get("PROMPTS_DIR")) is not None:
            values["prompts_dir"] = Path(raw).expanduser()
        if (raw := env.get("ALLOW_LIVE")) is not None:
            values["allow_live"] = _parse_bool("ALLOW_LIVE", raw)
        if (raw := env.get("LLM_FAKE")) is not None:
            values["llm_fake"] = _parse_bool("LLM_FAKE", raw)
        if (raw := get("CORS_ORIGINS")) is not None:
            values["cors_origins"] = tuple(o.strip() for o in raw.split(",") if o.strip())

        simple: dict[str, tuple[str, type]] = {
            "FR_BASE_URL": ("fr_base_url", str),
            "FR_TIMEOUT_S": ("fr_timeout_s", float),
            "FR_MAX_ATTEMPTS": ("fr_max_attempts", int),
            "FR_BACKOFF_BASE_S": ("fr_backoff_base_s", float),
            "FR_BACKOFF_MAX_S": ("fr_backoff_max_s", float),
            "FR_MARKDOWN_PAGE_CHARS": ("fr_markdown_page_chars", int),
            "OPENROUTER_BASE_URL": ("openrouter_base_url", str),
            "MODEL_MAIN": ("model_main", str),
            "MODEL_CHEAP": ("model_cheap", str),
            "LLM_TIMEOUT_S": ("llm_timeout_s", float),
            "LLM_MAX_TOKENS": ("llm_max_tokens", int),
            "PLAYGROUND_MAX_TOKENS": ("playground_max_tokens", int),
            "TOC_MATCH_THRESHOLD": ("toc_match_threshold", int),
            "CHAPTER_MATCH_THRESHOLD": ("chapter_match_threshold", int),
            "REPEATED_LINE_RATIO": ("repeated_line_ratio", float),
            "REPEATED_LINE_MIN_PAGES": ("repeated_line_min_pages", int),
            "MIN_BUSINESS_SECTIONS": ("min_business_sections", int),
            "GLUED_TITLE_MAX_CHARS": ("glued_title_max_chars", int),
            "CHARS_PER_TOKEN": ("chars_per_token", float),
            "FIN_MAX_YEARS": ("fin_max_years", int),
        }
        for env_name, (field, typ) in simple.items():
            if (raw := get(env_name)) is not None:
                try:
                    values[field] = typ(raw.strip())
                except ValueError as exc:
                    raise ValueError(f"{env_name} must be {typ.__name__}, got {raw!r}") from exc

        return cls(**values)

    def credential_flags(self) -> dict[str, bool]:
        """Whether each credential is configured, without revealing values (for /health)."""
        return {
            "fr_api_key": self.fr_api_key is not None,
            "openrouter_api_key": self.openrouter_api_key is not None,
        }


class MissingCredential(RuntimeError):
    """A live call needs a credential that is not configured."""

    def __init__(self, env_var: str, purpose: str):
        self.env_var = env_var
        super().__init__(f"{purpose} needs {env_var}; set it in the environment (see .env.example)")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()


def reset_settings_cache() -> None:
    get_settings.cache_clear()


__all__ = ["Settings", "MissingCredential", "get_settings", "reset_settings_cache"]
