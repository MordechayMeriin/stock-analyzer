"""Domain errors shared by the CLI, services and API.

Each error carries a machine-readable ``code``; the API maps codes to HTTP statuses
(see ``api/errors.py``). Messages never include credentials.
"""

from __future__ import annotations


class AnalyzerError(Exception):
    code = "internal_error"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class CompanyNotFound(AnalyzerError):
    code = "company_not_found"


class FilingNotFound(AnalyzerError):
    code = "filing_not_found"


class ReportNotFound(AnalyzerError):
    code = "report_not_found"


class NodeNotFound(AnalyzerError):
    code = "node_not_found"


class PageNotFound(AnalyzerError):
    code = "page_not_found"


class NotCached(AnalyzerError):
    """Cached-only mode needed data that is not cached. No network call was made."""

    code = "not_cached"


class LiveModeDisabled(AnalyzerError):
    code = "live_disabled"


class ReportSelectionError(AnalyzerError):
    code = "report_selection_failed"


class ProviderError(AnalyzerError):
    """The provider answered with an error status (after retries for 429/5xx)."""

    code = "upstream_error"

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class ProviderNotFound(ProviderError):
    code = "upstream_not_found"


class TruncatedContent(ProviderError):
    code = "upstream_truncated"


class ParseError(AnalyzerError):
    code = "parse_error"


class CurrencyMismatch(AnalyzerError):
    code = "currency_mismatch"


class SelectionTooLarge(AnalyzerError):
    code = "selection_too_large"


class ConfigurationError(AnalyzerError):
    code = "configuration_error"
