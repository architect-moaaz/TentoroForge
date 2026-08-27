"""Visual regression baseline (G7 / item 6).

The page sweep captures a full-page screenshot of every route on every
verify run. This module turns those captures into a regression signal:
a blessed **baseline** set lives in ``<app>/journeys/baseline/``, and
each later run's sweep screenshots are diffed against it pixel-wise
(with tolerance), so visual drift — a skin regression, a collapsed
layout, a vanished widget — is flagged even when every functional
check still passes.

Mechanics:
  - First run (no baseline): the current sweep is blessed automatically
    and the run reports ``blessed`` — a baseline you have to remember
    to create is a baseline that never exists.
  - Later runs: per matching screenshot, images are cropped to their
    common box and downscaled before a mean-absolute-difference
    compare (cheap, resolution-independent). Verdicts:
      ``ok`` (diff ≤ tolerance) · ``changed`` (diff above) ·
      ``layout_changed`` (dimensions drifted >10%) ·
      ``new`` / ``missing`` (page set changed).
  - Re-bless deliberately via ``bless_baseline`` (after an intentional
    design change) — never automatically once a baseline exists.

Report: contracts/visual-regression.json + attached to the verify
report by self_verify. Tolerance via FORGE_VISUAL_DIFF_TOLERANCE
(default 0.02 ≈ 2% mean pixel delta).
"""
from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

_MAX_COMPARE_WIDTH = 500  # downscale bound — diff signal, not forensics


def _tolerance() -> float:
    try:
        return float(os.environ.get("FORGE_VISUAL_DIFF_TOLERANCE") or 0.02)
    except ValueError:
        return 0.02


def _sweep_dir(root: Path) -> Path:
    return root / "journeys" / "artifacts" / "sweep"


def _baseline_dir(root: Path) -> Path:
    return root / "journeys" / "baseline"


def bless_baseline(output_dir: str | Path) -> dict:
    """Copy the current sweep captures into the baseline set."""
    root = Path(output_dir)
    src, dst = _sweep_dir(root), _baseline_dir(root)
    blessed: list[str] = []
    if src.is_dir():
        dst.mkdir(parents=True, exist_ok=True)
        for old in dst.glob("*.png"):
            old.unlink()
        for p in sorted(src.glob("*.png")):
            shutil.copy2(p, dst / p.name)
            blessed.append(p.name)
    if blessed:
        logger.info("[visual-regression] blessed %d baseline capture(s)",
                    len(blessed))
    return {"blessed": blessed}


def _diff_ratio(a_path: Path, b_path: Path) -> tuple[str, float]:
    """(verdict, ratio) for one screenshot pair."""
    from PIL import Image, ImageChops

    with Image.open(a_path) as a_img, Image.open(b_path) as b_img:
        aw, ah = a_img.size
        bw, bh = b_img.size
        if min(aw, bw) == 0 or min(ah, bh) == 0:
            return ("layout_changed", 1.0)
        # >10% drift in either dimension is a layout change, not a
        # pixel change — comparing crops would just mislead.
        if abs(aw - bw) / max(aw, bw) > 0.10 or abs(ah - bh) / max(ah, bh) > 0.10:
            return ("layout_changed", 1.0)
        box = (0, 0, min(aw, bw), min(ah, bh))
        a = a_img.convert("RGB").crop(box)
        b = b_img.convert("RGB").crop(box)
        if a.width > _MAX_COMPARE_WIDTH:
            scale = _MAX_COMPARE_WIDTH / a.width
            size = (_MAX_COMPARE_WIDTH, max(1, int(a.height * scale)))
            a = a.resize(size)
            b = b.resize(size)
        diff = ImageChops.difference(a, b)
        hist = diff.histogram()
        # Mean absolute channel delta, normalized to [0, 1].
        total = sum(hist[i % 256] * (i % 256) for i in range(len(hist)))
        pixels = a.width * a.height * 3
        ratio = (total / pixels / 255.0) if pixels else 0.0
    return ("ok" if ratio <= _tolerance() else "changed", round(ratio, 5))


def compare_to_baseline(output_dir: str | Path) -> dict:
    """Diff the current sweep against the blessed baseline. First run
    auto-blesses. Never raises."""
    root = Path(output_dir)
    sweep, baseline = _sweep_dir(root), _baseline_dir(root)
    report: dict = {"tolerance": _tolerance(), "results": [],
                    "summary": {"ok": 0, "changed": 0, "layout_changed": 0,
                                "new": 0, "missing": 0}}
    if not sweep.is_dir() or not any(sweep.glob("*.png")):
        report["skipped"] = "no sweep captures"
        return report
    if not baseline.is_dir() or not any(baseline.glob("*.png")):
        report["blessed"] = bless_baseline(root)["blessed"]
        _write(root, report)
        return report

    current = {p.name: p for p in sweep.glob("*.png")}
    blessed = {p.name: p for p in baseline.glob("*.png")}
    for name in sorted(current.keys() | blessed.keys()):
        if name not in blessed:
            verdict, ratio = "new", None
        elif name not in current:
            verdict, ratio = "missing", None
        else:
            try:
                verdict, ratio = _diff_ratio(blessed[name], current[name])
            except Exception as exc:  # noqa: BLE001
                logger.warning("[visual-regression] diff failed for %s: %s",
                               name, exc)
                continue
        report["results"].append({"page": name, "verdict": verdict,
                                  "diff_ratio": ratio})
        report["summary"][verdict] += 1

    drifted = report["summary"]["changed"] + report["summary"]["layout_changed"]
    if drifted:
        logger.warning("[visual-regression] %d page(s) drifted from the "
                       "baseline — see visual-regression.json", drifted)
    _write(root, report)
    return report


def _write(root: Path, report: dict) -> None:
    try:
        out = root / "contracts" / "visual-regression.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.warning("[visual-regression] could not write report: %s", exc)


__all__ = ["bless_baseline", "compare_to_baseline"]
