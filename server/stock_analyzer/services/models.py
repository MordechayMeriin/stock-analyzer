"""Response models returned by services; the API serializes these directly (one contract)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class CompanyOut(BaseModel):
    ticker: str
    name_he: str
    name_en: str | None = None
    fr_company_id: int
    isin: str | None = None


class CompanySearchHit(BaseModel):
    fr_company_id: int
    name: str
    ticker: str | None = None
    isin: str | None = None
    country_code: str | None = None
    tracked_ticker: str | None = None  # set when the hit is in the tracked registry


class FilingOut(BaseModel):
    filing_id: int
    title: str
    fiscal_year: int | None
    release_datetime: datetime | None
    file_extension: str | None
    file_size: int | None
    document_url: str | None
    viewer_url: str | None
    selected: bool  # the full annual report chosen for its fiscal year
    cached: bool  # its Markdown is saved locally


class FiscalYearFilings(BaseModel):
    fiscal_year: int
    selected_filing_id: int | None
    selection_error: str | None = None
    report_cached: bool
    filings: list[FilingOut]


class FilingsOut(BaseModel):
    ticker: str
    years: list[FiscalYearFilings]


class FetchedReport(BaseModel):
    fiscal_year: int
    filing_id: int
    total_chars: int
    path: str


class FetchOut(BaseModel):
    ticker: str
    reports: list[FetchedReport]
    financials_saved: bool
    credits_used: int
    network_calls: int


class UsageOut(BaseModel):
    provider: dict[str, Any] | None
    provider_error: str | None = None
    fr_log: dict[str, int]
    llm: dict[str, float | int]
