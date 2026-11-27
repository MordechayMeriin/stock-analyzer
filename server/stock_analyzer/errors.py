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


class MissingSubIndustry(AnalyzerError):
    code = "missing_sub_industry"


class CompanyAlreadyTracked(AnalyzerError):
    """The ticker or provider company id is already in the tracked companies."""

    code = "company_already_tracked"


class CompanyNotRemovable(AnalyzerError):
    """Companies from the version-controlled registry cannot be removed at runtime."""

    code = "company_not_removable"


class FilingNotFound(AnalyzerError):
    code = "filing_not_found"


class ReportNotFound(AnalyzerError):
    code = "report_not_found"


class NodeNotFound(AnalyzerError):
    code = "node_not_found"


class PageNotFound(AnalyzerError):
    code = "page_not_found"


class AxisNotFound(AnalyzerError):
    """No such report axis, or the axis has no score for the requested year (company-report spec)."""

    code = "axis_not_found"


class ReportVerificationFailed(AnalyzerError):
    """The rater's scores failed verification, also after their one repair (company-report spec)."""

    code = "report_verification_failed"

    def __init__(self, message: str, errors: list | None = None):
        super().__init__(message)
        self.errors = errors or []


class NotCached(AnalyzerError):
    """Cached-only mode needed data that is not cached. No network call was made."""

    code = "not_cached"


class LiveModeDisabled(AnalyzerError):
    code = "live_disabled"


class LiveModeRequired(AnalyzerError):
    """The operation only runs in live mode, and the request was in cached mode."""

    code = "live_required"


class ReportSelectionError(AnalyzerError):
    code = "report_selection_failed"


class ReportNotProcessed(AnalyzerError):
    """The provider has no Markdown for the selected filing (not yet processed, or not convertible)."""

    code = "report_not_processed"


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


class TemplateNotSupported(AnalyzerError):
    """The company's provider statement template has no canonical fields, so no ratios."""

    code = "template_not_supported"


class SelectionTooLarge(AnalyzerError):
    code = "selection_too_large"


class StoryTooLarge(AnalyzerError):
    """A story run would send more report text than the configured budget (company-story spec)."""

    code = "story_too_large"


class StoryReportsMissing(AnalyzerError):
    """Fewer than three annual reports were published by the story's as_of date."""

    code = "story_reports_missing"


class StoryVerificationFailed(AnalyzerError):
    """The story failed verification, also after its one repair attempt."""

    code = "story_verification_failed"

    def __init__(self, message: str, errors: list | None = None):
        super().__init__(message)
        self.errors = errors or []


class ConfigurationError(AnalyzerError):
    code = "configuration_error"


class StorageNotInitialized(AnalyzerError):
    """A database is configured but its schema has not been created (run ``stock-analyzer db init``)."""

    code = "configuration_error"


class StorageUnavailable(AnalyzerError):
    """The state store cannot be reached. Messages never include the connection string."""

    code = "storage_unavailable"


class NoFindings(AnalyzerError):
    """An OSINT run produced no finding that passed verification, so there is nothing to score."""

    code = "osint_no_findings"


class ResearchInProgress(AnalyzerError):
    """An OSINT run for the same ticker and window is already running in this server process."""

    code = "research_in_progress"


class StorySearchLimitExceeded(AnalyzerError):
    """The storyteller asked for more web searches than the story's limit; the run fails (company-story spec)."""

    code = "story_search_limit"

    def __init__(self, limit: int, queries: list[str]):
        self.limit = limit
        self.queries = list(queries)
        listed = "; ".join(repr(q) for q in queries)
        super().__init__(
            f"the storyteller asked for more than {limit} web searches (STORY_MAX_SEARCHES); nothing was saved. "
            f"Searches run: {listed}. A rerun with the same as_of replays the same turns from the cache and "
            "fails the same way: raise STORY_MAX_SEARCHES (or change the as_of) to retry"
        )
