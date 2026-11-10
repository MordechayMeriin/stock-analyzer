"""Write the API's OpenAPI document to ``server/openapi.json`` (the web client's type source).

uv run python scripts/export_openapi.py          # write
uv run python scripts/export_openapi.py --check  # exit 1 if the committed file is stale
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from stock_analyzer.api.main import create_app
from stock_analyzer.config import Settings

OUT = Path(__file__).resolve().parent.parent / "openapi.json"


def render() -> str:
    # fixed settings: the document must not depend on the local environment
    spec = create_app(Settings()).openapi()
    return json.dumps(spec, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> int:
    text = render()
    if "--check" in sys.argv:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print(f"{OUT} is stale: run `uv run python scripts/export_openapi.py`", file=sys.stderr)
            return 1
        print(f"{OUT} is up to date")
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT} ({len(text):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
