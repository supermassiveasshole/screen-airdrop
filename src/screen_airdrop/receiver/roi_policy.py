"""Receiver-side ROI policy normalization shared by CLI flows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from screen_airdrop.receiver.stats import TransferStats


@dataclass(frozen=True)
class RoiPolicy:
    mode: str
    interactive: bool
    pad_px: int
    manual_max_retries: int
    auto_fail_threshold: int
    report_mode: str

    @classmethod
    def from_args(cls, args) -> "RoiPolicy":
        interactive = bool(getattr(args, "roi_interactive", False))
        if getattr(args, "select_region", False):
            interactive = True
        mode = str(getattr(args, "roi_mode", "auto_then_manual"))
        if interactive and mode == "auto":
            mode = "auto_then_manual"
        elif interactive:
            mode = "manual"
        return cls(
            mode=mode,
            interactive=interactive,
            pad_px=max(0, int(getattr(args, "manual_roi_pad_px", 0))),
            manual_max_retries=max(0, int(getattr(args, "manual_max_retries", 1))),
            auto_fail_threshold=max(1, int(getattr(args, "auto_fail_threshold", 5))),
            report_mode="interactive" if interactive else mode,
        )

    def apply_to_args(self, args) -> None:
        args.roi_mode = self.mode
        args.roi_interactive = self.interactive
        args.select_region = self.interactive or bool(getattr(args, "select_region", False))
        args.manual_roi_pad_px = self.pad_px
        args.manual_max_retries = self.manual_max_retries
        args.auto_fail_threshold = self.auto_fail_threshold

    def manual_active(self, stats: TransferStats) -> bool:
        return self.mode == "manual" or stats.manual_roi_applied

    def needs_runtime_selection(
        self, *, source: str, forced_roi: Optional[Tuple[int, int, int, int]]
    ) -> bool:
        return (
            source == "screen"
            and self.mode == "auto_then_manual"
            and self.interactive
            and forced_roi is None
        )

    def requires_manual_roi(
        self, *, forced_roi: Optional[Tuple[int, int, int, int]]
    ) -> bool:
        return self.mode == "manual" and forced_roi is None and not self.interactive
