"""Project path resolution utilities for output-directory-based editor projects."""

from pathlib import Path

# Resolve to <repo-root>/output/
OUTPUT_ROOT = Path(__file__).resolve().parents[2] / "output"


def project_root(project_id: str) -> Path:
    """Resolve project_id to an output directory; reject path traversal."""
    if "/" in project_id or ".." in project_id or project_id.startswith("."):
        raise ValueError(f"invalid project id: {project_id!r}")
    p = (OUTPUT_ROOT / project_id).resolve()
    if not str(p).startswith(str(OUTPUT_ROOT.resolve())):
        raise ValueError(f"project id resolves outside output/: {project_id!r}")
    return p


def list_projects() -> list[dict]:
    """Return [{id, name}] for each non-hidden directory in OUTPUT_ROOT."""
    if not OUTPUT_ROOT.exists():
        return []
    out = []
    for entry in sorted(OUTPUT_ROOT.iterdir()):
        if entry.is_dir() and not entry.name.startswith("."):
            out.append({"id": entry.name, "name": entry.name})
    return out
