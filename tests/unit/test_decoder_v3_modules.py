from screen_airdrop.common.protocol_v3 import V3_FRAME_DATA, FrameHeaderV3
from screen_airdrop.receiver.decoder_v3 import _decode_from_modules_variants
from screen_airdrop.sender.encoder_v3 import build_symbol_modules_v3


def test_decode_v3_from_symbol_modules():
    payload = b"decoder-v3-modules"
    header = FrameHeaderV3.make(
        frame_type=V3_FRAME_DATA,
        session_id=99,
        epoch_id=1,
        frame_id=2,
        total_frames=10,
        chunk_id=2,
        payload=payload,
    )
    modules = build_symbol_modules_v3(header, payload, grid_w=160, grid_h=96, ecc_level="Q")
    parsed, restored, _, _ = _decode_from_modules_variants(modules, grid_w=160, grid_h=96)
    assert parsed.chunk_id == 2
    assert restored == payload
