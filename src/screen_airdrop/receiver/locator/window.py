"""Window location helper.

MVP behavior:
- If explicit region is provided, use it.
- Otherwise fallback to primary monitor.

This keeps receiver usable across platforms while we add native title-based
window lookup adapters incrementally.
"""

from __future__ import annotations

from typing import Optional, Tuple


def resolve_window_region(
    window_title: Optional[str],
    explicit_region: Optional[Tuple[int, int, int, int]],
    monitor_region: Tuple[int, int, int, int],
) -> Tuple[int, int, int, int]:
    if explicit_region is not None:
        return explicit_region

    # Placeholder: title-based mapping can be implemented with platform adapters.
    _ = window_title
    return monitor_region
