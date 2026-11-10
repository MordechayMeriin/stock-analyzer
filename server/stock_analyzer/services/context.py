"""Per-request service context: settings plus the cached/live mode (design D6)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from stock_analyzer.config import Settings
from stock_analyzer.errors import LiveModeDisabled
from stock_analyzer.ingest.fr_client import FRClient

Mode = Literal["cached", "live"]


@dataclass
class Ctx:
    settings: Settings
    mode: Mode = "cached"
    refresh: bool = False
    _fr: FRClient | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.mode not in ("cached", "live"):
            raise ValueError(f"mode must be 'cached' or 'live', got {self.mode!r}")
        if self.mode == "live" and not self.settings.allow_live:
            raise LiveModeDisabled(
                "live mode is disabled on this server (ALLOW_LIVE=false); only cached data can be served"
            )
        if self.refresh and self.mode != "live":
            raise ValueError("refresh needs live mode")

    @property
    def fr(self) -> FRClient:
        if self._fr is None:
            self._fr = FRClient(
                self.settings, mode="live" if self.mode == "live" else "cached", refresh=self.refresh
            )
        return self._fr

    def close(self) -> None:
        if self._fr is not None:
            self._fr.close()
