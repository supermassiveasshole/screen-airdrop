from screen_airdrop.receiver.cli import _should_use_pipeline


def test_pipeline_enabled_for_manual_mode_when_no_runtime_selection_needed():
    assert _should_use_pipeline(
        source="screen",
        protocol="basic",
        debug_dir=None,
        needs_runtime_roi_selection=False,
    )


def test_pipeline_disabled_when_runtime_manual_selection_is_required():
    assert not _should_use_pipeline(
        source="screen",
        protocol="basic",
        debug_dir=None,
        needs_runtime_roi_selection=True,
    )


def test_pipeline_disabled_by_debug_dir():
    assert not _should_use_pipeline(
        source="screen",
        protocol="basic",
        debug_dir="./debug",
        needs_runtime_roi_selection=False,
    )
