from __future__ import annotations

from screen_airdrop.sender.cli import legacy


def test_legacy_sender_forwards_experimental_coded_arguments(monkeypatch):
    captured = {}

    def _fake_run_sender(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(legacy, "run_sender", _fake_run_sender)

    rc = legacy.main(
        [
            "dummy.bin",
            "--emit-coded-units",
            "--coded-redundancy-count",
            "2",
            "--coded-degree",
            "3",
        ]
    )

    assert rc == 0
    assert captured["emit_coded_units"] is True
    assert captured["coded_redundancy_count"] == 2
    assert captured["coded_degree"] == 3


def test_legacy_sender_help_exposes_formal_coded_arguments():
    parser = legacy.build_parser()
    help_text = parser.format_help()

    assert "emit coded erasure units after systematic units" in help_text
    assert "experimental:" not in help_text
