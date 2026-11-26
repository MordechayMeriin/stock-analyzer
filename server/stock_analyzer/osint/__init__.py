"""OSINT stability research (osint-research spec, add-osint-research design).

Agents built with the OpenAI Agents SDK search the web through OpenRouter for open-source information
about a tracked company and turn it into a cited stability scorecard. The package never uses the
company's official filings: it imports nothing from ``ingest`` or ``fin`` and no report, filing or
financials service, and every search excludes the block-list in ``data/osint_blocklist.yaml``.
"""
