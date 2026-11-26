"""Filing-source block-list (design D3).

Entries follow OpenRouter's web plugin domain filter syntax: ``example.com`` matches the domain and its
subdomains, ``*.example.com`` only subdomains, and ``example.com/path`` a path prefix on that domain.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from stock_analyzer.config import SERVER_ROOT

DEFAULT_BLOCKLIST = SERVER_ROOT / "data" / "osint_blocklist.yaml"


@dataclass(frozen=True)
class _Entry:
    raw: str
    host: str
    subdomains_only: bool
    path: str  # "" = whole domain

    @classmethod
    def parse(cls, raw: str) -> _Entry:
        text = raw.strip().lower()
        if "://" in text:
            text = text.split("://", 1)[1]
        host, _, path = text.partition("/")
        subdomains_only = host.startswith("*.")
        if subdomains_only:
            host = host[2:]
        path = "/" + path.strip("/") if path.strip("/") else ""
        return cls(raw=raw.strip(), host=host, subdomains_only=subdomains_only, path=path)

    def matches(self, host: str, path: str) -> bool:
        if self.subdomains_only:
            host_ok = host.endswith("." + self.host)
        else:
            host_ok = host == self.host or host.endswith("." + self.host)
        if not host_ok:
            return False
        if not self.path:
            return True
        p = path.lower().rstrip("/")
        return p == self.path or p.startswith(self.path + "/")


@dataclass(frozen=True)
class Blocklist:
    entries: tuple[_Entry, ...]

    @property
    def exclude_domains(self) -> list[str]:
        """The entries as sent to the search provider."""
        return [e.raw for e in self.entries]

    def blocks(self, url: str) -> bool:
        """True when the URL is on the block-list (or cannot be parsed)."""
        try:
            parts = urlsplit(url.strip() if "://" in url else "https://" + url.strip())
        except ValueError:
            return True
        host = (parts.hostname or "").lower()
        if not host or "." not in host or any(c.isspace() for c in host):
            return True
        return any(e.matches(host, parts.path or "/") for e in self.entries)


def load_blocklist(ticker: str, path: Path = DEFAULT_BLOCKLIST) -> Blocklist:
    """Global entries plus the entries for this ticker."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw = list(data.get("global") or [])
    companies = {str(k).upper(): v for k, v in (data.get("companies") or {}).items()}
    raw += list(companies.get(ticker.upper()) or [])
    seen: dict[str, _Entry] = {}
    for item in raw:
        entry = _Entry.parse(str(item))
        seen.setdefault(entry.raw.lower(), entry)
    return Blocklist(entries=tuple(seen.values()))
