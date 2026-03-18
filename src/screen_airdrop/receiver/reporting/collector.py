"""Collector interfaces for modular metric collection."""

from abc import ABC, abstractmethod
from typing import Any, Dict


class Collector(ABC):
    """Abstract base class for metric collectors.

    Each collector is responsible for collecting a specific category
    of metrics (stats, protocol debug, assembler state, etc.).

    Collectors are designed to be composable and independent.
    """

    @abstractmethod
    def collect(self) -> Dict[str, Any]:
        """Collect current metrics.

        Returns:
            Dictionary of metrics to add to report
        """
        pass

    @abstractmethod
    def reset(self) -> None:
        """Reset collector state.

        This method is called when the collector needs to be reused
        for a new collection cycle.
        """
        pass


class EventCollector(Collector):
    """Collector that accumulates events during runtime.

    EventCollectors respond to decode success/failure events and
    accumulate protocol-specific debug information.

    Subclasses implement event handlers for specific event types.
    """

    @abstractmethod
    def on_decode_success(self, meta: Any) -> None:
        """Handle decode success event.

        Args:
            meta: Decode metadata object from decoder
        """
        pass

    @abstractmethod
    def on_decode_failure(
        self,
        error: str,
        failure_class: str,
        context: Dict[str, Any]
    ) -> None:
        """Handle decode failure event.

        Args:
            error: Error message
            failure_class: Failure classification (header, payload, locator, unknown)
            context: Optional context dictionary with protocol-specific details
        """
        pass
