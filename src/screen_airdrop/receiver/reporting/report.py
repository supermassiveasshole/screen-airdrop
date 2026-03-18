"""Report classes for receiver metrics.

This module provides the Report class - a pure data container with no business logic.
All metric collection is delegated to Collector classes.
"""

import json
import os
from typing import Any, Dict, Optional


class Report:
    """Pure data container with no business logic.

    Report is a simple dictionary wrapper that provides:
    - Type-safe data storage
    - JSON serialization
    - Immutability after finalization

    All metric collection is delegated to Collector classes.
    """

    def __init__(self):
        """Initialize empty report."""
        self.data: Dict[str, Any] = {}
        self._finalized = False

    def set(self, key: str, value: Any) -> None:
        """Set a single value in the report.

        Args:
            key: Field name
            value: Field value

        Raises:
            RuntimeError: If report is finalized
        """
        if self._finalized:
            raise RuntimeError("Cannot modify finalized report")
        self.data[key] = value

    def update(self, data: Dict[str, Any]) -> None:
        """Update multiple values.

        Args:
            data: Dictionary of fields to update

        Raises:
            RuntimeError: If report is finalized
        """
        if self._finalized:
            raise RuntimeError("Cannot modify finalized report")
        self.data.update(data)

    def get(self, key: str, default: Any = None) -> Any:
        """Get a value from the report.

        Args:
            key: Field name
            default: Default value if key not found

        Returns:
            Field value or default
        """
        return self.data.get(key, default)

    def finalize_simple(self) -> None:
        """Mark report as finalized (immutable).

        After finalization, no further modifications are allowed.
        """
        self._finalized = True

    def is_finalized(self) -> bool:
        """Check if report is finalized.

        Returns:
            True if finalized, False otherwise
        """
        return self._finalized

    def dump(self, path: Optional[str]) -> None:
        """Write report to JSON file.

        Args:
            path: Path to write report to (if None, no-op)
        """
        if not path:
            return
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def to_dict(self) -> Dict[str, Any]:
        """Get report data as dictionary.

        Returns:
            Copy of report data dictionary
        """
        return dict(self.data)

