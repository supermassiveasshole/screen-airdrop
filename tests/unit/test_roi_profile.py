from pathlib import Path

from screen_airdrop.receiver.roi_profile import load_profile, save_profile


def test_roi_profile_roundtrip(tmp_path: Path):
    p = tmp_path / "roi.json"
    save_profile(str(p), (10, 20, 300, 400), monitor_index=2)
    roi = load_profile(str(p))
    assert roi == (10, 20, 300, 400)
