"""Web evidence for the story: one source ledger, publish dates found by code (add-story-web-evidence).

Stored OSINT findings and the storyteller's live search hits go into one :class:`SourceLedger`
keyed by normalized URL (design D2). A source's id is derived from its URL, so the same page gets
the same id whether it came from the stored research run, a live search or both, and ids do not
change between reruns (later model turns' cache keys depend on them).

Publish dates are never taken from an LLM (design D3): stored findings keep the date the OSINT run
verified, and live hits get a date only if :func:`find_publish_date` finds one in their title or
excerpt.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date

from pydantic import BaseModel

from stock_analyzer.osint.blocklist import Blocklist
from stock_analyzer.osint.models import Area, KeptFinding, ResearchResult, SearchHit, Signal, normalize_url
from stock_analyzer.osint.search import SearchBackend, search_once
from stock_analyzer.osint.verify import parse_published
from stock_analyzer.store import Store, StoreLog


class WebSource(BaseModel):
    """One web page the story may cite."""

    source_id: str
    url: str
    title: str
    excerpts: list[str] = []  # provider excerpts, as returned; numbers are quoted only from these
    published_at: str | None = None  # YYYY-MM-DD, found by code; None when unknown
    stored: bool = False  # given to the story from the stored OSINT result
    live: bool = False  # returned by a storyteller search in this run
    # stored OSINT findings only
    finding_id: str | None = None
    area: Area | None = None
    claim: str | None = None
    signal: Signal | None = None
    derived_from_filing: bool = False

    @property
    def published(self) -> date | None:
        return date.fromisoformat(self.published_at) if self.published_at else None


def source_id(url: str) -> str:
    """``SRC:<n>``, derived from the normalized URL (stable across runs and origins)."""
    digest = hashlib.sha256(normalize_url(url).encode("utf-8")).hexdigest()
    return f"SRC:{int(digest[:8], 16) % 100_000_000}"


class SourceLedger:
    """The web sources of one story run, keyed by source id."""

    def __init__(self, sources: list[WebSource] | None = None):
        self._sources: dict[str, WebSource] = {}
        for s in sources or []:
            self._sources[s.source_id] = s

    def __contains__(self, sid: object) -> bool:
        return sid in self._sources

    def __len__(self) -> int:
        return len(self._sources)

    def get(self, sid: str) -> WebSource | None:
        return self._sources.get(sid)

    def sources(self) -> list[WebSource]:
        return list(self._sources.values())

    def stored(self) -> list[WebSource]:
        return [s for s in self._sources.values() if s.stored]

    def _entry(self, url: str, title: str) -> WebSource:
        sid = source_id(url)
        if sid not in self._sources:
            self._sources[sid] = WebSource(source_id=sid, url=url, title=title)
        return self._sources[sid]

    def add_stored(self, finding: KeptFinding) -> WebSource:
        src = self._entry(finding.source_url, finding.source_title)
        src.stored = True
        if src.finding_id is None:  # the first finding for a URL describes it
            src.finding_id = finding.id
            src.area = finding.area
            src.claim = finding.claim
            src.signal = finding.signal
        src.derived_from_filing = src.derived_from_filing or finding.derived_from_filing
        published = parse_published(finding.published_at)
        if published is not None and src.published_at is None:
            src.published_at = published.isoformat()
        if finding.excerpt and finding.excerpt not in src.excerpts:
            src.excerpts.append(finding.excerpt)
        return src

    def add_live(self, hit: SearchHit, published: date | None) -> WebSource:
        src = self._entry(hit.url, hit.title)
        src.live = True
        if not src.title and hit.title:
            src.title = hit.title
        if published is not None and src.published_at is None:
            src.published_at = published.isoformat()
        excerpt = hit.snippet.strip()
        if excerpt and excerpt not in src.excerpts:  # each search may return a different excerpt
            src.excerpts.append(excerpt)
        return src


# ---------------------------------------------------------------- the as_of filter


def within_as_of(published: date | None, as_of: date, today: date) -> bool:
    """Whether a source may reach a story written as of ``as_of`` (company-story spec).

    Sources dated after ``as_of`` never do. When ``as_of`` is before today, undated sources do not
    either: they could be from after ``as_of``."""
    if published is None:
        return as_of >= today
    return published <= as_of


def load_stored(ledger: SourceLedger, result: ResearchResult, as_of: date, today: date) -> int:
    """Add the stored findings that pass the ``as_of`` filter; returns how many were left out."""
    left_out = 0
    for finding in result.findings:
        if within_as_of(parse_published(finding.published_at), as_of, today):
            ledger.add_stored(finding)
        else:
            left_out += 1
    return left_out


# ---------------------------------------------------------------- publish dates

HEBREW_MONTHS = {
    "ינואר": 1, "פברואר": 2, "מרץ": 3, "מרס": 3, "אפריל": 4, "מאי": 5, "יוני": 6,
    "יולי": 7, "אוגוסט": 8, "ספטמבר": 9, "אוקטובר": 10, "נובמבר": 11, "דצמבר": 12,
}  # fmt: skip
ENGLISH_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}  # fmt: skip
_HE = "|".join(sorted(HEBREW_MONTHS, key=len, reverse=True))
_EN = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sept?|oct|nov|dec)[a-z]*\.?"

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)"), "ymd"),
    (re.compile(r"(?<![\d.])(\d{1,2})[./](\d{1,2})[./](\d{4})(?![\d])"), "dmy"),  # Israeli day-first
    (re.compile(rf"(?<!\d)(\d{{1,2}})\s+ב?({_HE})\s*,?\s*(\d{{4}})"), "d_he_y"),
    (re.compile(rf"(?<!\d)(\d{{1,2}})\s+({_EN})\s*,?\s*(\d{{4}})", re.IGNORECASE), "d_en_y"),
    (re.compile(rf"\b({_EN})\s+(\d{{1,2}}),?\s+(\d{{4}})", re.IGNORECASE), "en_d_y"),
]
PUBLICATION_WORDS = re.compile(
    r"(פורסם|פורסמה|עודכן|עודכנה|תאריך פרסום|published|updated|posted)\s*(?:on|ב|:)?\s*[:\-–]?\s*$",
    re.IGNORECASE,
)
DATE_WINDOW_CHARS = 300  # dates later in an excerpt are usually about events, not the page


def _to_date(kind: str, groups: tuple[str, ...]) -> date | None:
    try:
        if kind == "ymd":
            return date(int(groups[0]), int(groups[1]), int(groups[2]))
        if kind == "dmy":
            return date(int(groups[2]), int(groups[1]), int(groups[0]))
        if kind == "d_he_y":
            return date(int(groups[2]), HEBREW_MONTHS[groups[1]], int(groups[0]))
        if kind == "d_en_y":
            return date(int(groups[2]), ENGLISH_MONTHS[groups[1].lower()[:3]], int(groups[0]))
        if kind == "en_d_y":
            return date(int(groups[2]), ENGLISH_MONTHS[groups[0].lower()[:3]], int(groups[1]))
    except (ValueError, KeyError):
        return None
    return None


def find_publish_date(title: str, excerpt: str, today: date) -> date | None:
    """The publish date of a search hit, read by code from its title and the start of its excerpt.

    A date right after a publication word ("פורסם", "Published") wins; otherwise the first date.
    Dates after ``today`` are ignored (they are about the future, not the page). None when there
    is no usable date."""
    candidates: list[tuple[int, bool, date]] = []  # (position, after a publication word, date)
    for offset, text in ((0, title or ""), (len(title or "") + 1, (excerpt or "")[:DATE_WINDOW_CHARS])):
        for pattern, kind in _PATTERNS:
            for m in pattern.finditer(text):
                found = _to_date(kind, m.groups())
                if found is None or found > today or found.year < 1990:
                    continue
                marked = PUBLICATION_WORDS.search(text[max(0, m.start() - 30) : m.start()]) is not None
                candidates.append((offset + m.start(), marked, found))
    if not candidates:
        return None
    marked = [c for c in candidates if c[1]]
    return min(marked or candidates, key=lambda c: c[0])[2]


# ---------------------------------------------------------------- live search for the storyteller

STORY_SEARCH_PURPOSE = "story-search"


@dataclass
class StorySearch:
    """The storyteller's search state for one story run (design D4). It satisfies the shared search
    core's ``SearchState``, so the block-list, excerpt ledger and usage log are the OSINT ones."""

    backend: SearchBackend
    blocklist: Blocklist
    max_searches: int
    results_per_search: int
    as_of: date
    today: date
    store: Store | None = None  # the search cache lives in its llm namespace
    log: StoreLog | None = None
    used: int = 0  # counted across the first storyteller attempt and its repair
    queries: list[str] = field(default_factory=list)
    seen_urls: dict[str, SearchHit] = field(default_factory=dict)
    cost: float = 0.0
    fake: bool = False  # an offline run: its hits are cached under their own key

    def add_cost(self, cost: float | None) -> None:
        self.cost += cost or 0.0

    @property
    def left(self) -> int:
        return self.max_searches - self.used

    def cache_key(self, query: str) -> str:
        payload = json.dumps(
            {
                "query": query,
                "as_of": self.as_of.isoformat(),
                "results": self.results_per_search,
                "exclude": sorted(self.blocklist.exclude_domains),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        prefix = "story-search-fake:" if self.fake else "story-search:"  # fake hits never replay as real
        return prefix + hashlib.sha256(payload.encode("utf-8")).hexdigest()

    async def hits(self, query: str) -> tuple[list[SearchHit], int]:
        """(unblocked hits, blocked count) for ``query``: from the cache, or one provider search
        that is then cached. A cache hit is logged at zero cost, like a gateway cache hit."""
        cache = self.store.cache("llm") if self.store is not None else None
        key = self.cache_key(query)
        cached = cache.get(key) if cache is not None else None
        if cached is not None:
            if self.log is not None:
                self.log.write(
                    model=str(cached.get("model") or "cache"),
                    purpose=STORY_SEARCH_PURPOSE,
                    input_tokens=0,
                    output_tokens=0,
                    cost=0.0,
                    latency_ms=0,
                    cache_hit=True,
                    ok=True,
                    attempts=1,
                )
            found = [SearchHit(h["url"], h["title"], h["snippet"]) for h in cached["hits"]]
            for hit in found:
                self.seen_urls.setdefault(normalize_url(hit.url), hit)
            return found, int(cached.get("blocked") or 0)
        outcome = await search_once(self, self.backend, self.log, query, purpose=STORY_SEARCH_PURPOSE)
        if cache is not None:
            cache.set(
                key,
                {
                    "model": outcome.response.model,
                    "hits": [{"url": h.url, "title": h.title, "snippet": h.snippet} for h in outcome.hits],
                    "blocked": outcome.blocked,
                },
            )
        return outcome.hits, outcome.blocked
