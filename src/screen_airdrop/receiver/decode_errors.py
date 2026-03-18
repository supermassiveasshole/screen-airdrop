"""Protocol-specific decode error classes.

These error classes carry failure classification information from decoders
to the main process for accurate error reporting.

Information flow: Decoder → Error (with complete info) → Report (extract only)
"""

from typing import Any, Dict, Optional


class DecodeError(Exception):
    """Base class for decode errors with failure classification.

    Attributes:
        message: Error message
        failure_class: Failure classification (header, payload, locator, unknown)
        context: Optional protocol-specific context (RS layer, CRC values, etc.)
    """

    def __init__(
        self,
        message: str,
        failure_class: str = "unknown",
        context: Optional[Dict[str, Any]] = None,
    ):
        """Initialize decode error.

        Args:
            message: Error message
            failure_class: Failure classification
            context: Optional protocol-specific context
        """
        super().__init__(message)
        self.message = message
        self.failure_class = failure_class
        self.context = context or {}


# ============================================================================
# Gray4 Protocol Errors
# ============================================================================


class Gray4DecodeError(DecodeError):
    """Base class for gray4 protocol decode errors."""

    pass


class Gray4HeaderDecodeError(Gray4DecodeError):
    """Gray4 header decode error (format info, magic, header CRC)."""

    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None):
        super().__init__(message, failure_class="header", context=context)


class Gray4PayloadDecodeError(Gray4DecodeError):
    """Gray4 payload decode error (payload CRC mismatch)."""

    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None):
        super().__init__(message, failure_class="payload", context=context)


class Gray4LocatorDecodeError(Gray4DecodeError):
    """Gray4 locator/finder pattern detection error."""

    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None):
        super().__init__(message, failure_class="locator", context=context)


# ============================================================================
# Layered Protocol Errors
# ============================================================================


class LayeredDecodeError(DecodeError):
    """Base class for layered protocol decode errors."""

    pass


class LayeredBootstrapDecodeError(LayeredDecodeError):
    """Layered bootstrap layer decode error (RS, CRC, format parity)."""

    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None):
        super().__init__(message, failure_class="header", context=context)


class LayeredBodyDecodeError(LayeredDecodeError):
    """Layered body layer decode error (RS, CRC)."""

    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None):
        super().__init__(message, failure_class="payload", context=context)


class LayeredLocatorDecodeError(LayeredDecodeError):
    """Layered locator/finder pattern detection error."""

    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None):
        super().__init__(message, failure_class="locator", context=context)


# ============================================================================
# Basic/Compact Protocol Errors
# ============================================================================


class BasicDecodeError(DecodeError):
    """Base class for basic protocol decode errors."""

    pass


class BasicHeaderDecodeError(BasicDecodeError):
    """Basic header decode error."""

    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None):
        super().__init__(message, failure_class="header", context=context)


class BasicPayloadDecodeError(BasicDecodeError):
    """Basic payload decode error."""

    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None):
        super().__init__(message, failure_class="payload", context=context)


class BasicLocatorDecodeError(BasicDecodeError):
    """Basic locator/finder pattern detection error."""

    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None):
        super().__init__(message, failure_class="locator", context=context)
