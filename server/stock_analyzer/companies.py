"""Tracked-company registry: ``data/companies.yaml`` plus companies added at runtime, plan.md §1.2."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path
from typing import Literal, Protocol

import yaml
from pydantic import BaseModel

from stock_analyzer.errors import CompanyNotFound, ConfigurationError

log = logging.getLogger(__name__)

CompanySource = Literal["registry", "added"]


class CuratedPeer(BaseModel):
    """A hand-picked comparable issuer (provider ID), used instead of the sub-industry match."""

    fr_company_id: int
    name: str
    country: str  # ISO 3166-1 alpha-2 listing market; decides the cohort


class TrackedCompany(BaseModel):
    ticker: str
    name_he: str
    name_en: str | None = None
    fr_company_id: int
    isin: str | None = None
    # "registry": data/companies.yaml (version-controlled); "added": kept in the state store.
    source: CompanySource = "registry"
    # Curated benchmark peers (peer-benchmark spec); empty = select by exact ISIC sub-industry.
    peers: list[CuratedPeer] = []


@lru_cache(maxsize=8)
def _load(path: Path, mtime: float) -> tuple[TrackedCompany, ...]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError as exc:
        raise ConfigurationError(f"companies registry not found: {path}") from exc
    return tuple(
        TrackedCompany.model_validate({**c, "source": "registry"}) for c in data.get("companies", [])
    )


def load_companies(path: Path) -> list[TrackedCompany]:
    mtime = path.stat().st_mtime if path.exists() else 0.0
    return list(_load(path, mtime))


class _AddedSource(Protocol):
    def list_tracked(self) -> list[TrackedCompany]: ...


def load_registry(path: Path, store: _AddedSource) -> list[TrackedCompany]:
    """Tracked companies: the YAML list, then store-added ones that don't collide with it.

    The version-controlled list wins: an added company whose ticker or provider id is also in
    the YAML (committed after it was added) is skipped, with a warning, but not deleted.
    """
    merged = load_companies(path)
    for company in store.list_tracked():
        if (dup := find_duplicate(merged, company)) is not None:
            _warn_shadowed(company.ticker, dup.ticker)
            continue
        merged.append(company)
    return merged


@lru_cache(maxsize=64)
def _warn_shadowed(added: str, registry: str) -> None:
    log.warning(
        "added company %s is ignored: %s in companies.yaml has the same ticker or provider id",
        added,
        registry,
    )


def find_duplicate(companies: Iterable[TrackedCompany], candidate: TrackedCompany) -> TrackedCompany | None:
    """The first company sharing the candidate's ticker (case-insensitive) or provider id."""
    ticker = candidate.ticker.upper()
    for company in companies:
        if company.ticker.upper() == ticker or company.fr_company_id == candidate.fr_company_id:
            return company
    return None


def resolve_ticker(path: Path, ticker: str) -> TrackedCompany:
    """Resolve through the YAML list only (services use ``services.companies.resolve_company``)."""
    return find_ticker(load_companies(path), ticker)


def find_ticker(companies: Iterable[TrackedCompany], ticker: str) -> TrackedCompany:
    wanted = ticker.strip().upper()
    for company in companies:
        if company.ticker.upper() == wanted:
            return company
    raise CompanyNotFound(f"unknown ticker {ticker!r}: not in the tracked companies registry")
