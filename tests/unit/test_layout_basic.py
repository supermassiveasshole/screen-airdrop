from screen_airdrop.common.transport.layout_basic import LayoutInfoBasic, crc16_ccitt_false


def test_layout_pack_unpack_crc_roundtrip():
    layout = LayoutInfoBasic(
        layout_ver=1, quiet=4, finder=9, guard=2, grid_w=160, grid_h=96, timing_mode=1, flags=1
    )
    raw = layout.pack()
    parsed = LayoutInfoBasic.unpack(raw)
    assert parsed == layout
    assert crc16_ccitt_false(raw[:-2]) == int.from_bytes(raw[-2:], "little")
