"""Sender frame-stream generation helpers."""

from __future__ import annotations

import random
from dataclasses import asdict
from typing import Any, Dict, Generator, Optional

from screen_airdrop.common.control_plane import (
    CONTROL_FAMILY_BOOTSTRAP,
    CONTROL_FAMILY_GENERATION,
    CONTROL_KIND_GENERATION,
    CONTROL_KIND_LAYOUT,
    CONTROL_KIND_SESSION,
    CONTROL_WIRE_CHUNK_IDS,
    ControlPlaneItem,
)
from screen_airdrop.common.information import CodedUnit, CodingScheme, SystematicUnit
from screen_airdrop.common.transport import coded_payload_overhead_bytes, encode_coded_payload
from screen_airdrop.common.transport.protocol_basic import (
    ECC_LEVELS,
    ECC_Q,
    FRAME_DATA,
    FRAME_END,
    FRAME_SYNC,
    FrameHeaderBasic,
)
from screen_airdrop.common.transport.protocol_layered import normalize_layered_session_id
from screen_airdrop.sender.application.session_builder import build_sender_session
from screen_airdrop.sender.information import (
    build_coded_units,
    build_systematic_generation_plans,
)
from screen_airdrop.sender.scheduling.broadcast_schedule import BroadcastSchedule
from screen_airdrop.sender.scheduling.control_payloads import (
    build_generation_control_payload,
    build_layout_control_payload,
    build_session_control_payload,
)
from screen_airdrop.sender.scheduling.unit_schedule import (
    BroadcastUnitScheduler,
    CodedAugmentedBroadcastScheduler,
)
from screen_airdrop.sender.transport.factory import create_transport_encoder
from screen_airdrop.sender.transport.layered.encoder import (
    layered_body_profile_id_for_ecc_level,
    layered_profile_metadata,
)

DEFAULT_WIDTH = 1920
DEFAULT_HEIGHT = 1080


def build_encoded_frames(
    input_path: str,
    block_size: int = 6,
    chunk_size: Optional[int] = None,
    chunk_fill_ratio: float = 0.9,
    compress: str = "gzip",
    sync_frames: int = 8,
    manifest_repeat: int = 5,
    epochs: int = 1,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    session_id: Optional[int] = None,
    protocol: str = "basic",
    quiet_zone_px: int = 48,
    ecc_level: str = ECC_Q,
    module_grid: str = "160x96",
    guard_band_modules: int = 2,
    corner_size_modules: int = 9,
    outer_padding_px: int = 0,
    outer_padding_color: str = "black",
    schedule: Optional[BroadcastSchedule] = None,
    window_name: Optional[str] = None,
    systematic_generation_size: int = 256,
    emit_coded_units: bool = False,
    coded_redundancy_count: int = 0,
    coded_degree: int = 2,
    coded_scheme: CodingScheme = CodingScheme.GF256_SEED_V2,
) -> Generator[Dict[str, Any], None, None]:
    if session_id is None:
        session_id = random.getrandbits(64)
    outer_padding_white = outer_padding_color.lower() == "white"
    schedule = schedule or BroadcastSchedule(
        sync_frames=sync_frames,
        control_burst_repeat=manifest_repeat,
    )

    gw = 160
    gh = 96
    encoder = None
    if protocol == "basic":
        if ecc_level not in ECC_LEVELS:
            raise RuntimeError("invalid ecc-level: {0}".format(ecc_level))
        try:
            gw, gh = [int(p) for p in module_grid.lower().split("x")]
        except Exception as exc:
            raise RuntimeError("invalid module-grid {0}: {1}".format(module_grid, exc))
        version = 1
        encoder = create_transport_encoder(
            protocol=protocol,
            grid_w=gw,
            grid_h=gh,
            ecc_level=ecc_level,
            guard_band=guard_band_modules,
            corner_size=corner_size_modules,
            outer_padding_px=outer_padding_px,
            outer_padding_white=outer_padding_white,
        )
        layout_info = encoder.get_layout()
        cap = layout_info.data_capacity_bits // 8
    elif protocol == "compact":
        if ecc_level not in ECC_LEVELS:
            raise RuntimeError("invalid ecc-level: {0}".format(ecc_level))
        try:
            gw, gh = [int(p) for p in module_grid.lower().split("x")]
        except Exception as exc:
            raise RuntimeError("invalid module-grid {0}: {1}".format(module_grid, exc))
        version = 1
        encoder = create_transport_encoder(
            protocol=protocol,
            grid_w=gw,
            grid_h=gh,
            ecc_level=ecc_level,
            guard_band=1,
            corner_size=7,
            outer_padding_px=outer_padding_px,
            outer_padding_white=outer_padding_white,
        )
        layout_info = encoder.get_layout()
        cap = layout_info.data_capacity_bits // 8
    elif protocol == "gray4":
        if ecc_level not in ECC_LEVELS:
            raise RuntimeError("invalid ecc-level: {0}".format(ecc_level))
        try:
            gw, gh = [int(p) for p in module_grid.lower().split("x")]
        except Exception as exc:
            raise RuntimeError("invalid module-grid {0}: {1}".format(module_grid, exc))
        version = 1
        encoder = create_transport_encoder(
            protocol=protocol,
            grid_w=gw,
            grid_h=gh,
            ecc_level=ecc_level,
            guard_band=guard_band_modules,
            corner_size=corner_size_modules,
            outer_padding_px=outer_padding_px,
            outer_padding_white=outer_padding_white,
        )
        layout_info = encoder.get_layout()
        cap = layout_info.data_capacity_bits // 8
    elif protocol == "layered":
        try:
            gw, gh = [int(p) for p in module_grid.lower().split("x")]
        except Exception as exc:
            raise RuntimeError("invalid module-grid {0}: {1}".format(module_grid, exc))
        version = 1
        encoder = create_transport_encoder(
            protocol=protocol,
            grid_w=gw,
            grid_h=gh,
            ecc_level=ecc_level,
            guard_band=guard_band_modules,
            corner_size=corner_size_modules,
            outer_padding_px=outer_padding_px,
            outer_padding_white=outer_padding_white,
        )
        layout_info = encoder.get_layout()
        cap = layout_info.data_capacity_bits // 8
    else:
        raise ValueError(
            f"Protocol '{protocol}' not supported, use 'basic', 'compact', 'gray4', or 'layered'"
        )
    if protocol == "layered":
        session_id = normalize_layered_session_id(int(session_id))

    normalized_fill_ratio = max(0.05, min(1.0, float(chunk_fill_ratio)))
    robust_cap = min(int(cap), max(64, int(cap * normalized_fill_ratio)))
    effective_chunk_size = int(robust_cap)
    if bool(emit_coded_units):
        effective_chunk_size = max(1, int(effective_chunk_size - coded_payload_overhead_bytes()))
    requested_chunk_size = None if chunk_size is None else int(chunk_size)
    if requested_chunk_size is not None and requested_chunk_size > 0:
        if requested_chunk_size < effective_chunk_size:
            effective_chunk_size = requested_chunk_size
        elif requested_chunk_size > effective_chunk_size:
            print(
                "{0} chunk-size cap applied: requested={1} frame_capacity={2} fill_ratio={3:.2f} effective_cap={4}".format(
                    protocol,
                    requested_chunk_size,
                    cap,
                    normalized_fill_ratio,
                    effective_chunk_size,
                )
            )

    if effective_chunk_size > cap:
        raise RuntimeError(
            "chunk-size {0} exceeds frame payload capacity {1} at {2}x{3}/block={4}".format(
                effective_chunk_size, cap, width, height, block_size
            )
        )

    built = build_sender_session(
        input_path=input_path,
        compress=compress,
        chunk_size=effective_chunk_size,
        session_id=session_id,
    )
    control_items = list(built["control_items"])
    control_items.append(
        ControlPlaneItem(
            kind=CONTROL_KIND_SESSION,
            payload=build_session_control_payload(
                session_id=session_id,
                manifest=built["manifest"],
                protocol=protocol,
                window_name=window_name,
            ),
            wire_chunk_id=CONTROL_WIRE_CHUNK_IDS[CONTROL_KIND_SESSION],
        )
    )
    payload_chunks = list(built["payload_chunks"])
    generation_plans = build_systematic_generation_plans(
        session_id=int(session_id),
        payload_chunks=payload_chunks,
        systematic_generation_size=int(systematic_generation_size),
    )
    coded_redundancy_count = max(0, int(coded_redundancy_count))
    coded_degree = int(coded_degree)
    if not isinstance(coded_scheme, CodingScheme):
        coded_scheme = CodingScheme(str(coded_scheme))
    if bool(emit_coded_units) and coded_redundancy_count > 0 and coded_degree <= 0:
        raise ValueError("coded_degree must be positive when coded emission is enabled")
    coded_enabled = bool(emit_coded_units) and coded_redundancy_count > 0
    generation_coded_units = {}
    generation_coded_modes = {}
    generation_coded_degrees = {}
    for plan in generation_plans:
        if not coded_enabled:
            generation_coded_units[int(plan.generation_id)] = []
            generation_coded_modes[int(plan.generation_id)] = "disabled"
            generation_coded_degrees[int(plan.generation_id)] = 0
            continue
        if not _generation_supports_coded_units(plan.source_units):
            generation_coded_units[int(plan.generation_id)] = []
            generation_coded_modes[int(plan.generation_id)] = "skipped_variable_size"
            generation_coded_degrees[int(plan.generation_id)] = 0
            continue
        effective_coded_degree = min(int(coded_degree), int(plan.generation_size))
        generation_coded_units[int(plan.generation_id)] = build_coded_units(
            session_id=int(session_id),
            generation_id=int(plan.generation_id),
            generation_size=int(plan.generation_size),
            source_units=plan.source_units,
            count=coded_redundancy_count,
            coding_seed_start=0,
            degree=effective_coded_degree,
            coding_scheme=coded_scheme,
        )
        generation_coded_modes[int(plan.generation_id)] = "enabled"
        generation_coded_degrees[int(plan.generation_id)] = effective_coded_degree
    unit_scheduler = (
        CodedAugmentedBroadcastScheduler() if coded_enabled else BroadcastUnitScheduler()
    )
    first_generation_plan = generation_plans[0] if generation_plans else None
    first_generation_coded_units = (
        generation_coded_units.get(int(first_generation_plan.generation_id), [])
        if first_generation_plan is not None
        else []
    )
    control_items.append(
        ControlPlaneItem(
            kind=CONTROL_KIND_LAYOUT,
            payload=build_layout_control_payload(
                protocol=protocol,
                layout_info=layout_info,
                ecc_level=ecc_level,
                frame_payload_cap=cap,
                effective_chunk_size=effective_chunk_size,
                module_grid=module_grid,
            ),
            wire_chunk_id=CONTROL_WIRE_CHUNK_IDS[CONTROL_KIND_LAYOUT],
        )
    )
    control_burst_repeat = schedule.normalized_control_burst_repeat()
    sync_frames = schedule.normalized_sync_frames()
    data_realizations = schedule.normalized_data_realizations()
    coded_unit_count = sum(len(units) for units in generation_coded_units.values())
    payload_frame_count = (len(payload_chunks) + coded_unit_count) * data_realizations
    total_data_frames = (
        (len(control_items) * control_burst_repeat)
        + (len(generation_plans) * control_burst_repeat)
        + payload_frame_count
    )

    layered_profiles = (
        layered_profile_metadata(layered_body_profile_id_for_ecc_level(ecc_level))
        if protocol == "layered"
        else {}
    )
    metadata = {
        "session_id": session_id,
        "manifest": built["manifest"],
        "control_plane": [item.to_metadata() for item in control_items]
        + [
            {
                "kind": CONTROL_KIND_GENERATION,
                "family": CONTROL_FAMILY_GENERATION,
                "wire_chunk_id": CONTROL_WIRE_CHUNK_IDS[CONTROL_KIND_GENERATION],
                "payload_size": len(
                    build_generation_control_payload(
                        generation_id=0 if first_generation_plan is None else int(first_generation_plan.generation_id),
                        generation_size=0 if first_generation_plan is None else int(first_generation_plan.generation_size),
                        source_index_base=1 if first_generation_plan is None else int(first_generation_plan.source_index_base),
                        total_frames=total_data_frames,
                        payload_chunk_count=0 if first_generation_plan is None else int(first_generation_plan.generation_size),
                        effective_chunk_size=effective_chunk_size,
                        protocol=protocol,
                        coded_redundancy_count=len(first_generation_coded_units),
                        coded_degree=(
                            generation_coded_degrees.get(int(first_generation_plan.generation_id), 0)
                            if first_generation_plan is not None and first_generation_coded_units
                            else 0
                        ),
                        coded_payload_envelope=(
                            coded_scheme.value if first_generation_coded_units else ""
                        ),
                    )
                ),
            }
        ],
        "payload": built["payload"],
        "payload_chunks": payload_chunks,
        "payload_chunk_count": len(payload_chunks),
        "coded_unit_count": coded_unit_count,
        "coded_scheme": coded_scheme.value if coded_enabled else "",
        "systematic_generation_id": 0 if first_generation_plan is None else int(first_generation_plan.generation_id),
        "systematic_generation_size": len(payload_chunks) if len(generation_plans) <= 1 else int(systematic_generation_size),
        "systematic_generation_count": len(generation_plans),
        "emit_coded_units": bool(coded_enabled),
        "coded_redundancy_count": int(coded_redundancy_count),
        "coded_degree": int(coded_degree),
        "systematic_generations": [
            {
                "generation_id": int(plan.generation_id),
                "generation_size": int(plan.generation_size),
                "source_index_base": int(plan.source_index_base),
                "coded_redundancy_count": len(generation_coded_units.get(int(plan.generation_id), [])),
                "coded_degree_effective": int(
                    generation_coded_degrees.get(int(plan.generation_id), 0)
                ),
                "coded_emission_mode": str(generation_coded_modes.get(int(plan.generation_id), "disabled")),
            }
            for plan in generation_plans
        ],
        "payload_frame_count": payload_frame_count,
        "frame_payload_cap": cap,
        "total_data_frames": total_data_frames,
        "width": width,
        "height": height,
        "block_size": block_size,
        "chunk_size": effective_chunk_size,
        "effective_chunk_size": effective_chunk_size,
        "protocol_version": version,
        "quiet_zone_px": quiet_zone_px,
        "schedule": asdict(schedule),
        **layered_profiles,
    }

    for i in range(sync_frames):
        header = FrameHeaderBasic.make(
            frame_type=FRAME_SYNC,
            session_id=session_id,
            epoch_id=0,
            frame_id=i,
            total_frames=total_data_frames,
            chunk_id=0,
            payload=b"",
        )
        yield {
            "kind": "sync",
            "epoch": 0,
            "frame_id": i,
            "chunk_id": 0,
            "metadata": metadata,
            "image": encoder.encode_frame(header, b"", width=width, height=height),
        }

    def _yield_epoch(epoch: int):
        frame_id = 0
        for control_item in control_items:
            for _ in range(control_burst_repeat):
                header = FrameHeaderBasic.make(
                    frame_type=FRAME_DATA,
                    session_id=session_id,
                    epoch_id=epoch,
                    frame_id=frame_id,
                    total_frames=total_data_frames,
                    chunk_id=control_item.wire_chunk_id,
                    payload=control_item.payload,
                )
                yield {
                    "kind": "data",
                    "plane": "control",
                    "control_family": CONTROL_FAMILY_BOOTSTRAP,
                    "control_kind": control_item.kind,
                    "epoch": epoch,
                    "frame_id": frame_id,
                    "chunk_id": control_item.wire_chunk_id,
                    "metadata": metadata,
                    "image": encoder.encode_frame(
                        header,
                        control_item.payload,
                        width=width,
                        height=height,
                    ),
                }
                frame_id += 1

        for generation_plan in generation_plans:
            generation_item = ControlPlaneItem(
                kind=CONTROL_KIND_GENERATION,
                payload=build_generation_control_payload(
                    generation_id=int(generation_plan.generation_id),
                    generation_size=int(generation_plan.generation_size),
                    source_index_base=int(generation_plan.source_index_base),
                    total_frames=total_data_frames,
                    payload_chunk_count=int(generation_plan.generation_size),
                    effective_chunk_size=effective_chunk_size,
                    protocol=protocol,
                    coded_redundancy_count=len(
                        generation_coded_units.get(int(generation_plan.generation_id), [])
                    ),
                    coded_degree=int(
                        generation_coded_degrees.get(int(generation_plan.generation_id), 0)
                    ),
                    coded_payload_envelope=(
                        coded_scheme.value
                        if generation_coded_units.get(int(generation_plan.generation_id), [])
                        else ""
                    ),
                ),
                wire_chunk_id=CONTROL_WIRE_CHUNK_IDS[CONTROL_KIND_GENERATION],
            )
            for _ in range(control_burst_repeat):
                header = FrameHeaderBasic.make(
                    frame_type=FRAME_DATA,
                    session_id=session_id,
                    epoch_id=epoch,
                    frame_id=frame_id,
                    total_frames=total_data_frames,
                    chunk_id=generation_item.wire_chunk_id,
                    payload=generation_item.payload,
                )
                yield {
                    "kind": "data",
                    "plane": "control",
                    "control_family": CONTROL_FAMILY_GENERATION,
                    "control_kind": generation_item.kind,
                    "epoch": epoch,
                    "frame_id": frame_id,
                    "chunk_id": generation_item.wire_chunk_id,
                    "generation_id": int(generation_plan.generation_id),
                    "generation_size": int(generation_plan.generation_size),
                    "metadata": metadata,
                    "image": encoder.encode_frame(
                        header,
                        generation_item.payload,
                        width=width,
                        height=height,
                    ),
                }
                frame_id += 1

            coded_units = generation_coded_units.get(int(generation_plan.generation_id), [])
            if coded_units and isinstance(unit_scheduler, CodedAugmentedBroadcastScheduler):
                transmission_schedule = unit_scheduler.schedule_generation_units(
                    systematic_units=generation_plan.source_units,
                    coded_units=coded_units,
                    transport_epoch_id=epoch,
                    realization_count=data_realizations,
                )
            else:
                transmission_schedule = unit_scheduler.schedule_units(
                    generation_plan.source_units,
                    transport_epoch_id=epoch,
                    realization_count=data_realizations,
                )
            for scheduled in transmission_schedule.units:
                unit = scheduled.unit
                global_chunk_id = None
                is_coded = isinstance(unit, CodedUnit)
                if is_coded:
                    chunk_id = int(unit.equation_id) + 1
                    payload = encode_coded_payload(
                        equation_id=int(unit.equation_id),
                        coding_seed=int(unit.coding_seed),
                        degree=int(unit.degree),
                        coding_scheme=unit.coding_scheme,
                        payload=unit.payload,
                    )
                else:
                    chunk_id = int(getattr(unit, "source_index", 0))
                    global_chunk_id = int(generation_plan.source_index_base + chunk_id - 1)
                    payload = unit.payload
                header = FrameHeaderBasic.make(
                    frame_type=FRAME_DATA,
                    session_id=session_id,
                    epoch_id=int(scheduled.transport_epoch_id),
                    frame_id=frame_id,
                    total_frames=total_data_frames,
                    chunk_id=chunk_id,
                    payload=payload,
                )
                yield {
                    "kind": "data",
                    "plane": "data",
                    "control_family": None,
                    "control_kind": None,
                    "epoch": epoch,
                    "frame_id": frame_id,
                    "chunk_id": chunk_id,
                    "global_chunk_id": global_chunk_id,
                    "is_coded": bool(is_coded),
                    "realization_index": int(scheduled.realization_index),
                    "realization_count": int(scheduled.realization_count),
                    "generation_id": int(unit.generation_id),
                    "generation_size": int(unit.generation_size),
                    "source_index_base": int(generation_plan.source_index_base),
                    "equation_id": int(unit.equation_id) if is_coded else None,
                    "coding_seed": int(unit.coding_seed) if is_coded else None,
                    "degree": int(unit.degree) if is_coded else None,
                    "coding_scheme": str(unit.coding_scheme.value) if is_coded else None,
                    "transmission_unit": unit,
                    "metadata": metadata,
                    "image": encoder.encode_frame(
                        header,
                        payload,
                        width=width,
                        height=height,
                    ),
                }
                frame_id += 1

        end_header = FrameHeaderBasic.make(
            frame_type=FRAME_END,
            session_id=session_id,
            epoch_id=epoch,
            frame_id=frame_id,
            total_frames=total_data_frames,
            chunk_id=0,
            payload=b"",
        )
        yield {
            "kind": "end",
            "plane": "control",
            "control_family": "control",
            "control_kind": "end",
            "epoch": epoch,
            "frame_id": frame_id,
            "chunk_id": 0,
            "metadata": metadata,
            "image": encoder.encode_frame(end_header, b"", width=width, height=height),
        }

    epochs = int(epochs)
    if epochs <= 0:
        epoch = 0
        while True:
            yield from _yield_epoch(epoch)
            epoch += 1
    else:
        for epoch in range(epochs):
            yield from _yield_epoch(epoch)


def _generation_supports_coded_units(source_units) -> bool:
    sizes = {len(unit.payload) for unit in source_units if isinstance(unit, SystematicUnit)}
    return len(sizes) == 1 and bool(sizes)
