from __future__ import annotations

import numpy as np

from screen_airdrop.common.ecc_rs import (
    LAYERED_BODY_RS,
    LAYERED_BOOTSTRAP_RS,
    ReedSolomonError,
    decode_rs_bytes,
    decode_rs_bytes_with_erasures,
    encode_rs_bytes,
    rs_encoded_size,
)
from screen_airdrop.common.protocol_basic import FrameHeaderBasic
from screen_airdrop.common.protocol_layered import (
    BODY_META_STRUCT,
    BODY_TRAILER_SIZE,
    LAYERED_BODY_PROFILE_DENSE,
    LAYERED_BODY_PROFILE_ROBUST,
    LAYERED_BOOTSTRAP_REFERENCE_CELLS,
    LAYERED_BOOTSTRAP_ROWS,
    LAYERED_CONTROL_CELL_TEMPLATES,
    LAYERED_CONTROL_PATH_VERSION,
    LAYERED_MAGIC,
    LAYERED_VERSION,
    BootstrapFields,
    LayeredBodyMeta,
    build_body_raw_bytes,
    decode_body_raw_bytes,
    layered_body_profile_wire_id,
    layered_bootstrap_payload_size_bytes,
    layered_short_session_tag,
    normalize_layered_session_id,
)
from screen_airdrop.receiver.decoder_compact import _run_locator as _run_locator_compact
from screen_airdrop.receiver.decoder_gray4 import _sample_gray4_modules
from screen_airdrop.receiver.decoder_layered import (
    LayeredDecodeTraceError,
    _control_template_match,
    _decode_bootstrap_control_band,
    decode_frame_layered,
    decode_frame_layered_with_geometry,
)
from screen_airdrop.receiver.locator.basic import LocatorConfig
from screen_airdrop.receiver.protocol_adapter_layered import LayeredProtocolDecoder
from screen_airdrop.sender.encoder_layered import (
    build_layout_layered,
    encode_frame_layered,
    frame_capacity_bytes_layered,
)


def test_layered_bootstrap_pack_roundtrip():
    fields = BootstrapFields(
        magic=LAYERED_MAGIC,
        version=LAYERED_VERSION,
        frame_type=1,
        short_session_tag=layered_short_session_tag(123),
        body_profile_id=3,
        payload_len=1024,
        body_mask_id=3,
    )
    decoded = BootstrapFields.unpack(fields.pack())
    assert decoded == fields
    assert int(decoded.body_profile_wire_id) == int(layered_body_profile_wire_id(3))


def test_layered_session_id_is_normalized_to_16bit_transport_identity():
    session_id = 0x12345678
    assert normalize_layered_session_id(session_id) == 0x5678


def test_layered_body_meta_roundtrip():
    meta = LayeredBodyMeta(
        total_frames=77,
        chunk_id=12,
        payload_crc32=0x12345678,
        epoch_id=4,
        frame_id=9,
    )
    payload = b"hello layered"
    decoded_meta, decoded_payload = decode_body_raw_bytes(
        build_body_raw_bytes(meta, payload),
        len(payload),
    )
    assert decoded_meta == meta
    assert decoded_payload == payload


def test_layered_bootstrap_crc_failure():
    fields = BootstrapFields(
        magic=LAYERED_MAGIC,
        version=LAYERED_VERSION,
        frame_type=1,
        short_session_tag=layered_short_session_tag(123),
        body_profile_id=3,
        payload_len=32,
        body_mask_id=3,
    )
    bad = bytearray(fields.pack())
    bad[-1] ^= 0xFF
    try:
        BootstrapFields.unpack(bytes(bad))
    except ValueError as exc:
        assert "crc" in str(exc)
    else:
        raise AssertionError("expected bootstrap crc mismatch")


def test_layered_body_crc_failure():
    meta = LayeredBodyMeta(
        total_frames=7,
        chunk_id=3,
        payload_crc32=0x01020304,
        epoch_id=1,
        frame_id=8,
    )
    payload = b"layered payload"
    bad = bytearray(build_body_raw_bytes(meta, payload))
    bad[BODY_META_STRUCT.size] ^= 0x01
    try:
        decode_body_raw_bytes(bytes(bad), len(payload))
    except ValueError as exc:
        assert "crc" in str(exc)
    else:
        raise AssertionError("expected body crc mismatch")


def test_layered_layout_invariants():
    layout = build_layout_layered(grid_w=224, grid_h=136, guard_band=1, corner_size=7)
    assert layout.control_cells
    assert layout.bootstrap_cells
    assert layout.body_coords
    bootstrap_points = {point for cell in layout.bootstrap_cells for point in cell}
    control_points = {point for cell in layout.control_cells for point in cell}
    assert bootstrap_points.isdisjoint(set(layout.body_coords))
    assert control_points.isdisjoint(set(layout.body_coords))
    assert bootstrap_points.issubset(control_points)
    reference_points = {point for cell in layout.bootstrap_reference_cells for point in cell}
    assert reference_points
    assert reference_points.isdisjoint(bootstrap_points)
    isolation_y_cut = layout.base.grid_y0 + LAYERED_BOOTSTRAP_ROWS
    assert all(y < isolation_y_cut for _, y in bootstrap_points)
    assert all(y >= isolation_y_cut + 1 for _, y in layout.body_coords)
    expected_cap = layout.user_payload_capacity_bytes
    assert rs_encoded_size(LAYERED_BODY_RS, BODY_META_STRUCT.size + BODY_TRAILER_SIZE + expected_cap) <= layout.body_capacity_bytes
    assert rs_encoded_size(LAYERED_BODY_RS, BODY_META_STRUCT.size + BODY_TRAILER_SIZE + expected_cap + 1) > layout.body_capacity_bytes
    assert layout.user_payload_capacity_bytes == expected_cap
    assert frame_capacity_bytes_layered(224, 136, 1, 7) == expected_cap
    assert len(layout.bootstrap_cells) > 0
    assert len(layout.bootstrap_reference_cells) == LAYERED_BOOTSTRAP_REFERENCE_CELLS
    assert (layered_bootstrap_payload_size_bytes() + LAYERED_BOOTSTRAP_RS.nsym) * 8 <= layout.bootstrap_capacity_bits


def test_layered_vnext_dense_capacity_exceeds_previous_baseline():
    current_vnext_dense = frame_capacity_bytes_layered(
        240,
        144,
        1,
        7,
        body_profile_id=LAYERED_BODY_PROFILE_DENSE,
    )
    current_vnext_robust = frame_capacity_bytes_layered(
        240,
        144,
        1,
        7,
        body_profile_id=LAYERED_BODY_PROFILE_ROBUST,
    )
    assert current_vnext_dense > 7348
    assert current_vnext_dense > current_vnext_robust


def test_layered_vnext_dense_hits_224_target_ratio():
    gray4_l = 7530
    dense = frame_capacity_bytes_layered(
        224,
        136,
        1,
        7,
        body_profile_id=LAYERED_BODY_PROFILE_DENSE,
    )
    assert dense / gray4_l >= 0.92


def test_layered_bootstrap_rs_erasures_can_recover_single_corrupted_symbol():
    raw = BootstrapFields(
        magic=LAYERED_MAGIC,
        version=LAYERED_VERSION,
        frame_type=1,
        short_session_tag=layered_short_session_tag(123),
        body_profile_id=3,
        payload_len=32,
        body_mask_id=3,
    ).pack()
    coded = bytearray(encode_rs_bytes(LAYERED_BOOTSTRAP_RS, raw))
    coded[0] ^= 0xFF
    try:
        decode_rs_bytes(LAYERED_BOOTSTRAP_RS, bytes(coded))
    except ReedSolomonError:
        pass
    decoded, _errata = decode_rs_bytes_with_erasures(
        LAYERED_BOOTSTRAP_RS,
        bytes(coded),
        [0],
    )
    assert decoded == raw


def test_layered_control_templates_match_expected_symbols():
    dark = 24.0
    light = 228.0
    for symbol, template in enumerate(LAYERED_CONTROL_CELL_TEMPLATES):
        samples = [int(light if bit else dark) for bit in template]
        matched, best_score, confidence_margin = _control_template_match(samples, dark, light)
        assert matched == symbol
        assert best_score == 0.0
        assert confidence_margin > 0.0


def test_layered_control_band_decode_success():
    grid_w = 224
    grid_h = 136
    header = FrameHeaderBasic.make(
        frame_type=1,
        session_id=1234,
        epoch_id=2,
        frame_id=3,
        total_frames=9,
        chunk_id=5,
        payload=b"hello",
    )
    frame = encode_frame_layered(
        header,
        b"hello",
        width=1920,
        height=1080,
        grid_w=grid_w,
        grid_h=grid_h,
        guard_band=1,
        corner_size=7,
    )
    layout = build_layout_layered(grid_w, grid_h, 1, 7)
    loc, _engine, _new_err, _legacy_err = _run_locator_compact(
        frame=frame,
        locator_engine="auto",
        search_roi=None,
        cfg=LocatorConfig(grid_w=grid_w, grid_h=grid_h, guard_band=1, corner_size=7, confidence_threshold=0.55),
    )
    _, avg_gray_u8, *_rest = _sample_gray4_modules(loc.warped, layout.base)

    bootstrap, _rs_corr, trace = _decode_bootstrap_control_band(
        avg_gray_u8,
        layout,
        calibration_by_mask=None,
    )
    assert int(bootstrap.short_session_tag) == layered_short_session_tag(1234)
    assert int(trace["control_path_version"]) == int(LAYERED_CONTROL_PATH_VERSION)
    assert int(trace["bootstrap_attempt_count"]) >= 1
    assert str(trace["control_reference_decode_mode"]) == "reference_templates"
    assert trace["control_band_decode_stage"] == "ok"


def test_layered_control_band_decode_failure():
    layout = build_layout_layered(224, 136, 1, 7)
    avg_gray_u8 = np.zeros((layout.base.frame_h, layout.base.frame_w), dtype=np.uint8)
    try:
        _decode_bootstrap_control_band(avg_gray_u8, layout, calibration_by_mask=None)
    except LayeredDecodeTraceError as exc:
        assert str(exc) in {
            "bootstrap template match failed",
            "bootstrap rs decode failed",
            "bootstrap crc mismatch",
        }
        assert int(exc.trace.get("bootstrap_attempt_count", 0)) >= 1
    else:
        raise AssertionError("expected bootstrap fallback failure")


def test_layered_geometry_reuse_decode_matches_normal_decode():
    grid_w = 224
    grid_h = 136
    header = FrameHeaderBasic.make(
        frame_type=1,
        session_id=55,
        epoch_id=2,
        frame_id=34,
        total_frames=90,
        chunk_id=12,
        payload=b"geometry-lock",
    )
    payload = b"geometry-lock"
    frame = encode_frame_layered(
        header,
        payload,
        width=1920,
        height=1080,
        grid_w=grid_w,
        grid_h=grid_h,
        guard_band=1,
        corner_size=7,
    )
    decoded_header, decoded_payload, meta = decode_frame_layered(
        frame=frame,
        grid_w=grid_w,
        grid_h=grid_h,
        guard_band=1,
        corner_size=7,
    )
    decoder = LayeredProtocolDecoder(grid_w=grid_w, grid_h=grid_h, guard_band=1, corner_size=7)
    geometry = decoder.geometry_from_meta(meta)
    assert geometry is not None

    reused_header, reused_payload, reused_meta = decode_frame_layered_with_geometry(
        frame=frame,
        geometry=geometry,
        grid_w=grid_w,
        grid_h=grid_h,
        guard_band=1,
        corner_size=7,
    )

    assert int(decoded_header.chunk_id) == int(reused_header.chunk_id)
    assert int(decoded_header.frame_id) == int(reused_header.frame_id)
    assert decoded_payload == reused_payload
    assert reused_meta.geometry_reused is True
