"""Receiver-side ROI policy normalization shared by CLI flows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from screen_airdrop.receiver.reporting.transfer_stats import TransferStats


@dataclass(frozen=True)
class RoiPolicy:
    mode: str
    interactive: bool
    report_mode: str

    @classmethod
    def from_args(cls, args) -> "RoiPolicy":
        interactive = bool(getattr(args, "roi_interactive", False))
        has_manual_roi = bool(getattr(args, "roi", None))
        mode = "manual" if interactive or has_manual_roi else "auto"
        if interactive:
            return cls(mode="manual", interactive=True, report_mode="interactive")
        return cls(
            mode=mode,
            interactive=interactive,
            report_mode=mode,
        )

    def manual_active(self, stats: TransferStats) -> bool:
        return self.mode == "manual" or stats.manual_roi_applied

    def needs_runtime_selection(
        self, *, source: str, forced_roi: Optional[Tuple[int, int, int, int]]
    ) -> bool:
        del source, forced_roi
        return False

    def requires_manual_roi(
        self, *, forced_roi: Optional[Tuple[int, int, int, int]]
    ) -> bool:
        return self.mode == "manual" and forced_roi is None and not self.interactive
