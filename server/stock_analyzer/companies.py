"""Tracked-company registry (``data/companies.yaml``), plan.md §1.2."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel

from stock_analyzer.errors import CompanyNotFound, ConfigurationError


class TrackedCompany(BaseModel):
    ticker: str
    name_he: str
    name_en: str | None = None
    fr_company_id: int
    isin: str | None = None


@lru_cache(maxsize=8)
def _load(path: Path, mtime: float) -> tuple[TrackedCompany, ...]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError as exc:
        raise ConfigurationError(f"companies registry not found: {path}") from exc
    return tuple(TrackedCompany.model_validate(c) for c in data.get("companies", []))


def load_companies(path: Path) -> list[TrackedCompany]:
    mtime = path.stat().st_mtime if path.exists() else 0.0
    return list(_load(path, mtime))


def resolve_ticker(path: Path, ticker: str) -> TrackedCompany:
    wanted = ticker.strip().upper()
    for company in load_companies(path):
        if company.ticker.upper() == wanted:
            return company
    raise CompanyNotFound(f"unknown ticker {ticker!r}: not in the tracked companies registry")
