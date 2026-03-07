
from screen_airdrop.common.packing import build_payload_and_manifest, chunk_bytes


def test_chunk_roundtrip():
    data = b"a" * 100
    chunks = chunk_bytes(data, 16)
    assert b"".join(chunks) == data


def test_build_payload_manifest(tmp_path):
    p = tmp_path / "f.txt"
    p.write_text("hello")

    payload, manifest, chunks = build_payload_and_manifest(
        input_path=str(p),
        compress_method="gzip",
        chunk_size=32,
        session_id=1,
    )
    assert len(payload) > 0
    assert manifest.total_chunks == len(chunks)
    assert manifest.input_root_name == "f.txt"
