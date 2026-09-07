"""Tests for services.visual_regression — G7 baseline + pixel diff."""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from services.visual_regression import bless_baseline, compare_to_baseline


def _png(path: Path, color: tuple, size=(200, 300)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)


def _sweep(root: Path, name: str, color=(240, 240, 240), size=(200, 300)) -> None:
    _png(root / "journeys/artifacts/sweep" / name, color, size)


def _baseline(root: Path, name: str, color=(240, 240, 240), size=(200, 300)) -> None:
    _png(root / "journeys/baseline" / name, color, size)


def test_first_run_auto_blesses(tmp_path: Path):
    _sweep(tmp_path, "index.png")
    rep = compare_to_baseline(tmp_path)
    assert rep["blessed"] == ["index.png"]
    assert (tmp_path / "journeys/baseline/index.png").is_file()


def test_identical_pages_ok(tmp_path: Path):
    _sweep(tmp_path, "index.png")
    _baseline(tmp_path, "index.png")
    rep = compare_to_baseline(tmp_path)
    assert rep["summary"]["ok"] == 1
    assert rep["results"][0]["verdict"] == "ok"
    assert rep["results"][0]["diff_ratio"] == 0.0


def test_visual_drift_flagged(tmp_path: Path):
    _sweep(tmp_path, "index.png", color=(240, 240, 240))
    _baseline(tmp_path, "index.png", color=(20, 20, 60))   # skin regression
    rep = compare_to_baseline(tmp_path)
    assert rep["summary"]["changed"] == 1
    assert rep["results"][0]["diff_ratio"] > 0.02


def test_small_noise_within_tolerance(tmp_path: Path):
    _sweep(tmp_path, "index.png", color=(240, 240, 240))
    _baseline(tmp_path, "index.png", color=(238, 238, 238))  # ~1% delta
    rep = compare_to_baseline(tmp_path)
    assert rep["summary"]["ok"] == 1


def test_dimension_drift_is_layout_changed(tmp_path: Path):
    _sweep(tmp_path, "index.png", size=(200, 600))
    _baseline(tmp_path, "index.png", size=(200, 300))
    rep = compare_to_baseline(tmp_path)
    assert rep["summary"]["layout_changed"] == 1


def test_new_and_missing_pages_tracked(tmp_path: Path):
    _sweep(tmp_path, "index.png")
    _sweep(tmp_path, "reports.png")          # new page this run
    _baseline(tmp_path, "index.png")
    _baseline(tmp_path, "archive.png")       # page that vanished
    rep = compare_to_baseline(tmp_path)
    assert rep["summary"]["new"] == 1
    assert rep["summary"]["missing"] == 1


def test_existing_baseline_never_auto_reblessed(tmp_path: Path):
    _sweep(tmp_path, "index.png", color=(0, 0, 0))
    _baseline(tmp_path, "index.png", color=(255, 255, 255))
    compare_to_baseline(tmp_path)
    with Image.open(tmp_path / "journeys/baseline/index.png") as img:
        assert img.getpixel((0, 0)) == (255, 255, 255)  # baseline untouched


def test_explicit_bless_replaces_baseline(tmp_path: Path):
    _sweep(tmp_path, "index.png", color=(0, 0, 0))
    _baseline(tmp_path, "index.png", color=(255, 255, 255))
    _baseline(tmp_path, "stale.png")
    rep = bless_baseline(tmp_path)
    assert rep["blessed"] == ["index.png"]
    assert not (tmp_path / "journeys/baseline/stale.png").exists()
    with Image.open(tmp_path / "journeys/baseline/index.png") as img:
        assert img.getpixel((0, 0)) == (0, 0, 0)


def test_report_written(tmp_path: Path):
    _sweep(tmp_path, "index.png")
    _baseline(tmp_path, "index.png")
    compare_to_baseline(tmp_path)
    rep = json.loads((tmp_path / "contracts/visual-regression.json").read_text(encoding="utf-8"))
    assert rep["summary"]["ok"] == 1


def test_no_sweep_skips(tmp_path: Path):
    rep = compare_to_baseline(tmp_path)
    assert rep["skipped"] == "no sweep captures"
