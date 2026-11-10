"""Shared Hebrew text normalization (plan.md §1.4, report-parsing spec).

The same function is used everywhere text is compared (parser, structure matching,
later the diff and claim verification), so two spellings of the same text always agree.

Steps: strip bidi control characters → strip Markdown emphasis and inline HTML
(``**``, ``__``, ``<u>``, ``<br>``, other tags, HTML comments) → unify geresh/gershayim
and typographic quotes with ASCII quotes → unescape HTML entities → collapse whitespace.
"""

from __future__ import annotations

import html
import re

# LRM, RLM, ALM, LRE/RLE/PDF/LRO/RLO, LRI/RLI/FSI/PDI, BOM, zero-width chars
_BIDI = re.compile("[​-‏‪-‮⁦-⁩؜﻿­]")
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_BR = re.compile(r"<br\s*/?>", re.I)
_TAG = re.compile(r"</?(?:u|b|i|em|strong|sup|sub|span|p|div|s|del|ins|mark|small)(?:\s[^>]*)?>", re.I)
_EMPHASIS = re.compile(r"(\*\*|__)")
_SPACES = re.compile(r"[ \t  -   　]+")
_QUOTES = str.maketrans(
    {
        "״": '"',  # ״ Hebrew gershayim
        "“": '"',
        "”": '"',
        "„": '"',
        "׳": "'",  # ׳ Hebrew geresh
        "‘": "'",
        "’": "'",
        "‚": "'",
        "´": "'",
        "`": "'",
    }
)


def strip_bidi(text: str) -> str:
    return _BIDI.sub("", text)


def normalize(text: str, *, keep_newlines: bool = False) -> str:
    """Normalize text for display and comparison.

    With ``keep_newlines`` line structure is preserved (each line collapsed separately);
    otherwise all whitespace, newlines included, collapses to single spaces.
    """
    t = strip_bidi(text)
    t = _COMMENT.sub(" ", t)
    t = _BR.sub(" ", t)
    t = _TAG.sub("", t)
    t = _EMPHASIS.sub("", t)
    # unescape twice: provider text sometimes double-escapes (&amp;amp;)
    t = html.unescape(html.unescape(t))
    t = t.translate(_QUOTES)
    t = strip_bidi(t)  # entities may decode to bidi controls (&lrm;)
    if keep_newlines:
        lines = (_SPACES.sub(" ", line).strip() for line in t.splitlines())
        return "\n".join(lines).strip()
    return " ".join(t.split())


def normalize_title(text: str) -> str:
    """Normalization for matching titles: :func:`normalize`, then drop Markdown heading
    markers, list bullets and surrounding punctuation."""
    t = normalize(text)
    t = re.sub(r"^(?:#+|[-*•]\s)\s*", "", t)
    return t.strip(" .:-–|")
