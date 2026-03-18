"""Protocol configuration constants and utilities."""

from typing import Tuple

# Protocol geometry configuration
# Maps protocol name to (guard_band, corner_size) tuple
PROTOCOL_GEOMETRY = {
    "compact": (1, 7),
    "gray4": (1, 7),
    "layered": (1, 7),
    "basic": (2, 9),
}


def get_protocol_geometry(protocol: str) -> Tuple[int, int]:
    """Get guard_band and corner_size for protocol.

    Args:
        protocol: Protocol name (basic, compact, gray4, layered)

    Returns:
        Tuple of (guard_band, corner_size)
        Returns (2, 9) as default for unknown protocols
    """
    return PROTOCOL_GEOMETRY.get(protocol, (2, 9))
