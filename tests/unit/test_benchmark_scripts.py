from bench.benchmark_common import ProtocolConfig, make_decoder, make_encoder
from bench.compare_end_to_end import _screen_runbook_case
from bench.compare_protocols import benchmark_protocol


def test_screen_runbook_case_contains_controlled_commands():
    config = ProtocolConfig("compact", grid_w=166, grid_h=102)
    result = _screen_runbook_case(
        config=config,
        layout_mode="footprint_matched",
        ecc_level="Q",
        payload_mode="max",
        payload_size=500,
        fps=12,
        capture_fps=30,
        benchmark_seconds=45,
        stats_interval=1.0,
        input_path="tests/fixtures/real_data/regular_pdf",
    )

    assert result["benchmark_kind"] == "end_to_end_screen_runbook"
    assert result["benchmark_goal"] == "rate_only"
    assert result["benchmark_seconds"] == 45
    assert result["layout_mode"] == "footprint_matched"
    assert "--protocol compact" in result["sender_command"]
    assert "--module-grid 166x102" in result["sender_command"]
    assert "--chunk-size 594" in result["sender_command"]
    assert "regular_pdf" in result["sender_command"]
    assert "--roi-interactive" in result["receiver_command"]
    assert "--max-seconds 45" in result["receiver_command"]


def test_synthetic_benchmark_reports_payload_efficiency():
    config = ProtocolConfig("basic", grid_w=160, grid_h=96)
    encoder = make_encoder(config, "Q")
    decoder = make_decoder(config)
    result = benchmark_protocol(
        protocol_name=config.protocol,
        config=config,
        encoder=encoder,
        decoder=decoder,
        ecc_level="Q",
        layout_mode="same_grid",
        payload_mode="fixed",
        payload_size=500,
        iterations=1,
        width=1920,
        height=1080,
    )

    assert result["benchmark_kind"] == "synthetic_cpu"
    assert result["payload_bytes"] == 500
    assert result["payload_bits_per_module"] > 0
    assert result["synthetic_cpu_kib_per_s"] > 0
