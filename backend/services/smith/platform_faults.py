"""A fault in what Forge writes is reported to Forge, beside the fix in the app (2026-10-31).

Smith fixes the application; the platform's people fix the platform. Some
faults are the platform's even when Smith meets them in one app: the drawing
converter left every drawn control without the hand cursor, the page wrapper
put the public bar over drawn public screens, the sign-up route gave a person
a role no portal offered (DITANS, 2026-10-31). Fixed only in the app's copy,
each comes back in the next app — and in this one at the next projection.

So Smith does both: fixes the app's copy now, and files the fault for the
platform with what shows it, which part of Forge writes the file, and the
change it proposes there. Reports land in one list across every app
(`_platform_patches/faults.jsonl`, read by the super admin's platform-patch
view); the same fault filed again from the same app is counted, not repeated.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

FAULTS_FILE = "faults.jsonl"

#: Who in Forge writes a generated file — the part the fix belongs to.
WRITERS: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"^src/components/drawn/"), "the drawing converter (services/drawn: convert, params, tsx), "
                                             "into `drawnViews`"),
    (re.compile(r"^src/components/(DrawnShell|DrawnShellLoad|DrawnFrame)\."), "the drawn shell projector "
                                                                             "(services/drawn/project.py)"),
    (re.compile(r"^src/app/.*/(page|loading)\.tsx$"), "the page wrapper (services/blueprint/app_sdk.py `page_module`)"),
    (re.compile(r"^src/lib/account(-table)?\.ts$"), "the account model (services/blueprint/account_model.py)"),
    (re.compile(r"^src/sdk/"), "the app SDK (services/blueprint/app_sdk.py, templates/app-foundation/src/sdk)"),
    (re.compile(r"^src/app/api/"), "the app foundation (templates/app-foundation/src/app/api)"),
    (re.compile(r"^src/lib/workflows/definitions/"), "the workflow projection (services/blueprint/projection.py)"),
    (re.compile(r"^src/lib/(workflows|data-engine|runtime)"), "the runtime (templates/runtime)"),
    (re.compile(r"^src/db/seed"), "the seeder (templates/runtime/seed.ts, projection `project_seed`)"),
    (re.compile(r"^src/app/\(dashboard\)/[A-Z]\w*\.tsx$|^src/app/\(dashboard\)/layout\.tsx$|^src/components/Public"),
     "the platform's frame (templates/app-foundation; `sync_app.FRAME_FILES`)"),
)


def writer_of(path: str) -> str:
    """The part of Forge that writes `path` (under the app), or ""."""
    rel = str(path or "").strip().lstrip("/")
    rel = rel[4:] if rel.startswith("app/") else rel
    return next((who for rx, who in WRITERS if rx.search(rel)), "")


def _registry(output_dir: str | Path) -> Path:
    from services.smith.file_edit import REGISTRY_DIR
    return Path(output_dir).parent / REGISTRY_DIR / FAULTS_FILE


def report(output_dir: str, summary: str, *, path: str = "", evidence: str = "", proposal: str = "",
           app_fix: str = "") -> dict:
    """File one platform fault. The write tool's envelope."""
    summary = " ".join(str(summary or "").split())
    if not summary or not proposal.strip():
        text = ("A platform fault needs `summary` (what is wrong, in one sentence) and `proposal` (the change "
                "Forge should make, in its own terms).")
        return {"applied": False, "said": text, "finding": text, "touched": [], "version": 0}
    app = Path(output_dir).name
    key = hashlib.sha1(f"{app}|{summary.lower()}|{path}".encode()).hexdigest()[:12]
    entry = {"id": f"fault-{key}", "app": app, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "summary": summary, "path": path, "writer": writer_of(path), "evidence": str(evidence)[:2000],
             "proposal": str(proposal)[:2000], "appFix": str(app_fix)[:1000]}
    reg = _registry(output_dir)
    seen = [f for f in open_faults(reg.parent.parent) if f.get("id") == entry["id"]]
    try:
        reg.parent.mkdir(parents=True, exist_ok=True)
        with reg.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({**entry, "times": len(seen) + 1}, ensure_ascii=False) + "\n")
    except OSError as exc:
        text = f"The fault could not be filed: {exc}"
        return {"applied": False, "said": text, "finding": text, "touched": [], "version": 0}
    said = (f"Reported to the platform team" + (" again" if seen else "") + f": {summary}"
            + (f" (written by {entry['writer']})" if entry["writer"] else "") + ".")
    return {"applied": True, "said": said, "finding": "", "touched": [], "version": 0}


def open_faults(output_root: str | Path) -> list[dict]:
    """Every filed fault, the latest line per fault, newest first."""
    from services.smith.file_edit import REGISTRY_DIR
    path = Path(output_root) / REGISTRY_DIR / FAULTS_FILE
    latest: dict[str, dict] = {}
    try:
        for line in path.read_text("utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            latest[str(row.get("id"))] = row
    except OSError:
        return []
    return sorted(latest.values(), key=lambda r: str(r.get("at")), reverse=True)


__all__ = ["FAULTS_FILE", "WRITERS", "open_faults", "report", "writer_of"]
