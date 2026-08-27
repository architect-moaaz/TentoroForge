"""Bridge script injection for the visual editor.

Copies the bridge.js overlay script into the generated app's public folder
and ensures the root layout loads it via next/script.
"""

import re
import shutil
from pathlib import Path

BRIDGE_SRC = Path(__file__).parent.parent / "static" / "bridge.js"
SCRIPT_TAG = '<Script src="/__bridge.js" strategy="afterInteractive" />'
SCRIPT_IMPORT = "import Script from 'next/script'"


def inject_bridge(output_dir: str) -> None:
    """Copy bridge.js into public/ and add Script tag to root layout."""
    out = Path(output_dir)
    public = out / "public"
    public.mkdir(parents=True, exist_ok=True)
    shutil.copy2(BRIDGE_SRC, public / "__bridge.js")

    # Find root layout.tsx
    layout = _find_layout(out)
    if not layout:
        return

    source = layout.read_text()

    # Already injected?
    if "__bridge.js" in source:
        return

    # Add import for next/script if missing
    if SCRIPT_IMPORT not in source:
        # Insert after the last import line
        lines = source.split("\n")
        last_import_idx = -1
        for i, line in enumerate(lines):
            if line.strip().startswith("import "):
                last_import_idx = i
        if last_import_idx >= 0:
            lines.insert(last_import_idx + 1, SCRIPT_IMPORT)
            source = "\n".join(lines)

    # Insert Script tag before </body>
    if "</body>" in source:
        source = source.replace("</body>", f"        {SCRIPT_TAG}\n      </body>")
    else:
        # Try inserting before the closing of the root element in JSX
        # Look for the pattern: </html> or last closing tag
        source = re.sub(
            r"(</html>)",
            f"        {SCRIPT_TAG}\n      \\1",
            source,
            count=1,
        )

    layout.write_text(source)


def remove_bridge(output_dir: str) -> None:
    """Remove bridge script and Script tag from the generated app."""
    out = Path(output_dir)

    # Delete the bridge file
    bridge_file = out / "public" / "__bridge.js"
    if bridge_file.exists():
        bridge_file.unlink()

    # Remove Script tag and import from layout
    layout = _find_layout(out)
    if not layout:
        return

    source = layout.read_text()
    # Remove the Script tag line
    source = re.sub(r"\s*<Script\s+src=\"/__bridge\.js\"[^/]*/>\s*\n?", "\n", source)
    # Remove the Script import if no other Script usage remains
    if "<Script " not in source:
        source = source.replace(SCRIPT_IMPORT + "\n", "")
        source = source.replace(SCRIPT_IMPORT, "")
    layout.write_text(source)


def _find_layout(out: Path) -> Path | None:
    """Locate the root layout.tsx file."""
    candidates = [
        out / "src" / "app" / "layout.tsx",
        out / "app" / "layout.tsx",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None
