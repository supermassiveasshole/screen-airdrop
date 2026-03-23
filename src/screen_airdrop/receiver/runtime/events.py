"""Event and data classes for runtime pipeline."""

from dataclasses import dataclass
from typing import Any, Dict, Optional

from screen_airdrop.receiver.locator.state_machine import GeometryState


@dataclass(frozen=True)
class FrameSlotDescriptor:
    """Descriptor for a frame slot."""

    slot_id: int
    generation: int
    capture_index: int
    ts: float
    width: int
    height: int
    fingerprint: bytes
    flags: int = 0
    dump_requested: bool = False
    slot_kind: str = "capture"


@dataclass(frozen=True)
class FilledSlotEvent:
    """Event: slot filled with captured frame."""

    descriptor: FrameSlotDescriptor
    grab_ms: float
    copy_ms: float = 0.0


@dataclass(frozen=True)
class PreparedSlotEvent:
    """Event: slot prepared (fingerprinted, not duplicate)."""

    descriptor: FrameSlotDescriptor
    fingerprint: bytes
    fingerprint_ms: float
    dedup_score: float
    dedup_decision_ms: float


@dataclass(frozen=True)
class DuplicateSlotEvent:
    """Event: slot is duplicate frame."""

    descriptor: FrameSlotDescriptor
    fingerprint: bytes
    fingerprint_ms: float
    dedup_score: float
    dedup_decision_ms: float = 0.0


@dataclass(frozen=True)
class PrepFingerprintEvent:
    """Event: fingerprint computed (process mode)."""

    descriptor: FrameSlotDescriptor
    fingerprint: bytes
    fingerprint_ms: float


@dataclass(frozen=True)
class DecodeAssignment:
    """Assignment for decode worker."""

    descriptor: FrameSlotDescriptor
    stream_id: str
    geometry_generation: int
    decode_owner: str
    dump_requested: bool
    geometry_state: Optional[GeometryState]
    forced_roi: Optional[tuple[int, int, int, int]]


@dataclass(frozen=True)
class DecodeCompletion:
    """Decode completion result."""

    descriptor: FrameSlotDescriptor
    worker_id: int
    success: bool
    error: str = ""
    failure_class: str = ""
    context: Optional[Dict[str, Any]] = None
    meta: Any = None
    frame_id: int = -1
    frame_type: int = -1
    chunk_id: int = -1
    payload: bytes = b""
    control_kind: str = ""
    transmission_unit: Any = None
    decode_mode: str = ""
    decode_quality: float = 0.0
    decode_attach_ms: float = 0.0
    used_geometry_generation: int = -1
    proposed_geometry_state: Optional[GeometryState] = None


@dataclass(frozen=True)
class DumpCopyCompletion:
    """Dump copy completion result."""

    descriptor: FrameSlotDescriptor
    copied: bool
    dump_ms: float = 0.0
    error: str = ""
