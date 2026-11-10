"""Server-sent events helpers (design D5): ``event: delta|done|error`` with JSON data."""

from __future__ import annotations

import json
from typing import Any


def sse_event(event: str, data: Any) -> dict[str, str]:
    payload = data.model_dump(mode="json") if hasattr(data, "model_dump") else data
    return {"event": event, "data": json.dumps(payload, ensure_ascii=False)}
