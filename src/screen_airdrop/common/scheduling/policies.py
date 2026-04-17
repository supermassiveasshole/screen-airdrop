"""Shared scheduling-policy skeletons."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OgrbPolicy:
    """Skeleton OGRB policy parameters."""

    systematic_budget: int = 1
    coded_budget: int = 0
    revisit_window: int = 0
    allow_overlap: bool = False
