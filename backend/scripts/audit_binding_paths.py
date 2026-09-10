"""List every {{binding}} path used across all page schemas in a project.
Usage: python3 backend/scripts/audit_binding_paths.py <short_id>
Output: one path per line, sorted, deduped. Exits 1 if the schemas dir doesn't exist.
"""
import json, re, sys
from pathlib import Path


def audit(short_id: str) -> None:
    base = Path(__file__).resolve().parents[2] / "output" / short_id / "src" / "schemas"
    if not base.exists():
        print(f"No schemas dir at {base}", file=sys.stderr)
        sys.exit(1)
    paths: set[str] = set()
    for f in base.rglob("*.json"):
        try:
            text = f.read_text(encoding="utf-8")
        except OSError:
            continue
        # Match {{anything that isn't a closing brace or pipe}} — strip pipe
        # filters so 'name | default("x")' becomes 'name'.
        for m in re.findall(r"\{\{([^}|]+?)(?:\s*\|[^}]*)?\}\}", text):
            paths.add(m.strip())
    for p in sorted(paths):
        print(p)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: audit_binding_paths.py <short_id>", file=sys.stderr)
        sys.exit(2)
    audit(sys.argv[1])
