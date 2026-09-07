# backend/services/bank_promotion.py
"""Auto-promotion of high-scoring real generations into the reference bank.

Daily/manual scan over output/<id>/src/contracts/fidelity-log.json files.
Pages scoring >= 8.5 with no high-severity issues land in
backend/reference_pages/<register>/<domain>/<page_type>/.candidates/
for human review before being promoted.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_PROMOTE_SCORE_THRESHOLD = 8.5


def find_candidates(output_root: Path) -> list[dict[str, Any]]:
    """Scan all projects' fidelity-log.json. Return candidates that meet
    the auto-promotion criteria but haven't been promoted yet."""
    candidates: list[dict[str, Any]] = []
    if not output_root.exists():
        return candidates

    for proj_dir in sorted(output_root.iterdir()):
        if not proj_dir.is_dir():
            continue
        log_path = proj_dir / "src" / "contracts" / "fidelity-log.json"
        spec_path = proj_dir / "src" / "contracts" / "design-spec.json"
        if not log_path.exists():
            continue

        try:
            log = json.loads(log_path.read_text(encoding="utf-8"))
            spec = json.loads(spec_path.read_text(encoding="utf-8")) if spec_path.exists() else {}
        except json.JSONDecodeError:
            continue

        register = spec.get("register", "default")
        domain = spec.get("domain", "general")

        for page_path, entry in log.items():
            final_score = entry.get("final_score", 0.0)
            if final_score < _PROMOTE_SCORE_THRESHOLD:
                continue
            iters = entry.get("iterations", [])
            if not iters:
                continue
            last_iter = iters[-1]
            issues = last_iter.get("issues", [])
            has_high = any(i.get("severity") == "high" for i in issues)
            if has_high:
                continue
            # Find the schema file
            schema_path = proj_dir / "src" / "schemas" / f"{page_path}.json"
            if not schema_path.exists():
                continue
            candidates.append({
                "project_id": proj_dir.name,
                "page_path": page_path,
                "register": register,
                "domain": domain,
                "page_type": _infer_page_type_from_path(page_path),
                "score": final_score,
                "schema_path": str(schema_path),
            })

    return candidates


def _infer_page_type_from_path(page_path: str) -> str:
    # Normalise: treat both "/" and "_" as separators for suffix matching
    last = page_path.replace("/", "_").split("_")[-1] if page_path else ""
    if last in ("list", "index") or page_path.endswith("/list") or page_path.endswith("/index"):
        return "list"
    if last in ("new", "edit", "create") or page_path.endswith("/new") or page_path.endswith("/edit"):
        return "form"
    if "dashboard" in page_path or page_path.endswith("/overview") or last == "dashboard":
        return "dashboard"
    if "settings" in page_path:
        return "settings"
    if last == "detail" or page_path.endswith("/detail") or "[id]" in page_path:
        return "detail"
    return "generic"


def promote_candidate(candidate: dict[str, Any], bank_root: Path) -> Path:
    """Copy the candidate schema + screenshot into the reference bank."""
    register = candidate["register"]
    domain = candidate["domain"]
    page_type = candidate["page_type"]

    cell = bank_root / register / domain / page_type
    cell.mkdir(parents=True, exist_ok=True)

    # Find next exemplar number
    existing = sorted(cell.glob("exemplar_*.json"))
    next_idx = len(existing) + 1
    stem = f"exemplar_{next_idx:02d}"

    schema_text = Path(candidate["schema_path"]).read_text(encoding="utf-8")
    (cell / f"{stem}.json").write_text(schema_text, encoding="utf-8")
    (cell / f"{stem}.meta.json").write_text(json.dumps({
        "score": candidate["score"],
        "promoted_from": candidate["project_id"],
        "promoted_page": candidate["page_path"],
        "auto_promoted": True,
    }, indent=2), encoding="utf-8")

    return cell / f"{stem}.json"
