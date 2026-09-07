"""Page section parser — maps route to page file and extracts sections via AST.

Supplements the bridge DOM tree with richer AST-parsed section data
(component names, prop info) for the section outline panel.
"""

import asyncio
import json
import os
from pathlib import Path


# Common Next.js App Router route-to-file mapping
def _route_to_page_file(output_dir: str, route: str) -> str | None:
    """Map a route like '/dashboard' to its page.tsx file."""
    base = Path(output_dir)

    # Normalize route
    route = route.strip("/") or ""

    # Possible file locations in App Router
    candidates = []
    if route == "":
        candidates = [
            base / "src" / "app" / "page.tsx",
            base / "app" / "page.tsx",
        ]
    else:
        candidates = [
            base / "src" / "app" / route / "page.tsx",
            base / "app" / route / "page.tsx",
        ]

    for candidate in candidates:
        if candidate.exists():
            return str(candidate.relative_to(base))

    return None


async def parse_page_sections(
    output_dir: str,
    route: str,
) -> dict:
    """Parse the page file for a given route and extract section structure.

    Uses the parse-sections.mjs Babel script if available, falls back to
    a simple regex-based parser.

    Returns:
        {
            "page_file": "src/app/page.tsx",
            "sections": [
                {
                    "tagName": "section",
                    "componentName": "HeroSection",
                    "line": 24,
                    "children_count": 3,
                },
                ...
            ],
        }
    """
    page_file = _route_to_page_file(output_dir, route)
    if not page_file:
        return {"page_file": None, "sections": []}

    abs_path = os.path.join(output_dir, page_file)

    # Try Babel AST script
    script_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "static",
        "parse-sections.mjs",
    )

    if os.path.exists(script_path):
        try:
            proc = await asyncio.create_subprocess_exec(
                "node",
                script_path,
                abs_path,
                output_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=output_dir,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode == 0 and stdout:
                result = json.loads(stdout.decode())
                return {
                    "page_file": page_file,
                    "sections": result.get("sections", []),
                }
        except Exception:
            pass

    # Fallback: simple regex parsing
    sections = _regex_parse_sections(abs_path)
    return {"page_file": page_file, "sections": sections}


def _regex_parse_sections(filepath: str) -> list[dict]:
    """Simple regex-based section extraction as fallback."""
    try:
        content = Path(filepath).read_text(encoding="utf-8")
    except Exception:
        return []

    import re

    sections = []
    # Find JSX elements that look like sections
    pattern = re.compile(
        r"<((?:header|nav|main|section|article|aside|footer|[A-Z]\w+))\b",
    )
    lines = content.splitlines()
    for i, line in enumerate(lines):
        for m in pattern.finditer(line):
            tag = m.group(1)
            is_component = tag[0].isupper()
            sections.append({
                "tagName": tag.lower() if not is_component else tag,
                "componentName": tag if is_component else None,
                "line": i + 1,
                "children_count": 0,
            })

    return sections
