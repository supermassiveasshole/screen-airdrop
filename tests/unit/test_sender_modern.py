from __future__ import annotations

from screen_airdrop.sender.cli import modern


def test_modern_sender_uses_black_outer_padding_for_gray4(monkeypatch):
    captured: dict[str, object] = {}

    def _fake_run_sender(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(modern, "run_sender", _fake_run_sender)

    rc = modern.main(
        [
            "dummy.bin",
            "--protocol",
            "gray4",
        ]
    )

    assert rc == 0
    assert captured["outer_padding_color"] == "black"


def test_modern_sender_forwards_experimental_coded_arguments(monkeypatch):
    captured: dict[str, object] = {}

    def _fake_run_sender(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(modern, "run_sender", _fake_run_sender)

    rc = modern.main(
        [
            "dummy.bin",
            "--emit-coded-units",
            "--coded-redundancy-count",
            "3",
            "--coded-degree",
            "4",
        ]
    )

    assert rc == 0
    assert captured["emit_coded_units"] is True
    assert captured["coded_redundancy_count"] == 3
    assert captured["coded_degree"] == 4


def test_modern_sender_help_exposes_formal_coded_arguments():
    parser = modern.build_parser()
    help_text = parser.format_help()

    assert "emit coded erasure units after systematic units" in help_text
    assert "experimental:" not in help_text
