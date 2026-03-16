import importlib.util
import json
from pathlib import Path


def _load_module():
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / "bench" / "analyze_gray4_triplet.py"
    spec = importlib.util.spec_from_file_location("analyze_gray4_triplet", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_main_writes_json(monkeypatch, tmp_path, capsys):
    module = _load_module()

    def _fake_analyze_frame(path, grid_w, grid_h, assume_mask_id=None):
        return {"file": Path(path).name, "grid": f"{grid_w}x{grid_h}", "decode": {"ok": True}}

    monkeypatch.setattr(module, "analyze_frame", _fake_analyze_frame)
    output_path = tmp_path / "triplet.json"

    rc = module.main(
        [
            "--module-grid",
            "240x144",
            "--assume-mask-id",
            "3",
            "--frames",
            "a.png",
            "b.png",
            "--output-json",
            str(output_path),
        ]
    )

    assert rc == 0
    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert [item["file"] for item in data] == ["a.png", "b.png"]
    assert "240x144" in capsys.readouterr().out


def test_transition_density_helpers():
    module = _load_module()
    import numpy as np

    modules = np.array(
        [
            [0, 0, 1, 1],
            [0, 1, 1, 0],
            [3, 3, 2, 2],
        ],
        dtype=np.uint8,
    )

    density = module._transition_density(modules)
    assert density["horizontal"] > 0.0
    assert density["vertical"] > 0.0
    assert density["combined"] > 0.0

    rows = module._top_transition_lines(modules, axis=0, top_n=2)
    cols = module._top_transition_lines(modules, axis=1, top_n=2)
    assert len(rows) == 2
    assert len(cols) == 2
    assert "transition_density" in rows[0]
    assert "transition_density" in cols[0]


def test_symbol_helpers():
    module = _load_module()
    import numpy as np

    symbols = np.array([0, 0, 1, 2, 2, 3], dtype=np.uint8)
    hist = module._symbol_hist(symbols)
    balance = module._symbol_balance(symbols)
    assert hist == {"0": 2, "1": 1, "2": 2, "3": 1}
    assert balance["mean"] > 0.0
    assert balance["std"] > 0.0


def test_header_bit_analysis_empty():
    module = _load_module()
    import numpy as np

    result = module._header_bit_analysis(
        avg_gray_u8=np.zeros((2, 2), dtype=np.uint8),
        header_modules=np.zeros((2, 2), dtype=np.uint8),
        sample_stack_u8=np.zeros((9, 2, 2), dtype=np.uint8),
        thresholds=[],
        layout=type("Layout", (), {"data_coords": [], "frame_w": 2})(),
        mask_id=3,
        repetition=1,
    )
    assert result["selected_threshold"] == -1
    assert result["weakest_bits"] == []


def test_payload_symbol_analysis_orders_weakest_first():
    module = _load_module()
    import numpy as np

    layout = type(
        "Layout",
        (),
        {"data_coords": [(0, 0), (1, 0), (0, 1)], "frame_w": 2},
    )()
    adaptive = np.array([[0, 1], [2, 3]], dtype=np.uint8)
    avg_gray = np.array([[10, 80], [150, 240]], dtype=np.uint8)
    confidences = [0.8, 0.1, 0.4, 0.9]

    result = module._payload_symbol_analysis(
        avg_gray_u8=avg_gray,
        adaptive_modules=adaptive,
        confidences=confidences,
        layout=layout,
    )
    assert result["weakest_symbols"][0]["confidence"] == 0.1
