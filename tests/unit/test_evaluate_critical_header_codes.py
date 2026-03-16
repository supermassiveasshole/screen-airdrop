from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from screen_airdrop.common.protocol_basic import FRAME_DATA, FrameHeaderBasic


def _load_module():
    script_path = (
        Path(__file__).resolve().parents[2] / "bench" / "evaluate_critical_header_codes.py"
    )
    spec = importlib.util.spec_from_file_location("evaluate_critical_header_codes", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _make_header() -> FrameHeaderBasic:
    payload = bytes(range(32))
    return FrameHeaderBasic.make(
        frame_type=FRAME_DATA,
        session_id=0x1122334455667788,
        epoch_id=2,
        frame_id=41,
        total_frames=300,
        chunk_id=10,
        payload=payload,
    )


def test_critical_header_roundtrip() -> None:
    module = _load_module()
    critical = module.CriticalHeaderV0.from_full_header(_make_header())
    decoded = module.CriticalHeaderV0.unpack(critical.pack())
    assert decoded == critical
    tiny = module.TinyHeaderV0.from_full_header(_make_header())
    tiny_decoded = module.TinyHeaderV0.unpack(tiny.pack())
    assert tiny_decoded == tiny


def test_short_code_candidates_decode_clean_channel() -> None:
    module = _load_module()
    for header_cls in (module.CriticalHeaderV0, module.TinyHeaderV0):
        header = header_cls.from_full_header(_make_header())
        message_bits = module._bits_from_bytes(header.pack())
        for candidate in module._candidate_table(len(message_bits)):
            encoded = candidate["encode"](message_bits)
            decoded_bits = candidate["decode_scores"]([1.0 if bit else -1.0 for bit in encoded])
            decoded = header_cls.unpack(module._bytes_from_bits(decoded_bits))
            assert decoded == header


def test_short_code_candidates_fit_within_current_header_cells() -> None:
    module = _load_module()
    for header_cls in (module.CriticalHeaderV0, module.TinyHeaderV0):
        header = header_cls.from_full_header(_make_header())
        message_bits = module._bits_from_bytes(header.pack())
        code_bits = {
            item["name"]: len(item["encode"](message_bits))
            for item in module._candidate_table(len(message_bits))
        }
        assert code_bits["critical_hamming74"] < 336
        assert code_bits["critical_secded84"] < 336
        assert code_bits["critical_repetition_2"] < 336
