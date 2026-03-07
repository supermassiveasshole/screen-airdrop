from screen_airdrop.common.manifest import Manifest


def test_manifest_json_roundtrip():
    m = Manifest(
        protocol_version=1,
        session_id=1,
        created_at="2026-01-01T00:00:00Z",
        input_root_name="x",
        pack="tar",
        compress="gzip",
        chunk_size=16,
        total_chunks=2,
        payload_size=32,
        payload_sha256="abc",
        entries=[],
    )
    m2 = Manifest.from_json_bytes(m.to_json_bytes())
    assert m2.session_id == 1
    assert m2.compress == "gzip"
