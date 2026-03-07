from screen_airdrop.common.layout_v31 import LayoutInfoV31, crc16_ccitt_false


def test_layout_pack_unpack_crc_roundtrip():
    layout = LayoutInfoV31(layout_ver=1, quiet=4, finder=9, guard=2, grid_w=160, grid_h=96, timing_mode=1, flags=1)
    raw = layout.pack()
    parsed = LayoutInfoV31.unpack(raw)
    assert parsed == layout
    assert crc16_ccitt_false(raw[:-2]) == int.from_bytes(raw[-2:], "little")
