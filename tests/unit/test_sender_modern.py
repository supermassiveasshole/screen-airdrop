from __future__ import annotations

from screen_airdrop.sender import modern


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

