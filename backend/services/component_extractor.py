"""Component extractor — finds the enclosing React component for a given line.

Used by the visual editor to scope AI edits to just the relevant component
instead of running the full refiner agent against the entire project.
"""

import re
from pathlib import Path


def extract_component_context(
    output_dir: str,
    file: str,
    line: int,
) -> dict | None:
    """Find the enclosing component function for a given source line.

    Returns a dict with:
        component_name: str
        source: str          — the component function source code
        start_line: int
        end_line: int
        file: str            — relative file path

    Returns None if the component cannot be determined.
    """
    filepath = Path(output_dir) / file
    if not filepath.exists():
        return None

    try:
        lines = filepath.read_text(encoding="utf-8").splitlines()
    except Exception:
        return None

    if line < 1 or line > len(lines):
        return None

    # Scan backwards from target line to find the component function declaration
    comp_start = None
    comp_name = None

    # Patterns for component declarations
    func_pattern = re.compile(
        r"^export\s+(?:default\s+)?(?:async\s+)?function\s+(\w+)"
    )
    const_pattern = re.compile(
        r"^(?:export\s+(?:default\s+)?)?const\s+(\w+)\s*[=:]\s*"
    )

    for i in range(line - 1, -1, -1):
        stripped = lines[i].lstrip()
        m = func_pattern.match(stripped)
        if m:
            comp_name = m.group(1)
            comp_start = i
            break
        m = const_pattern.match(stripped)
        if m:
            # Check if this looks like a component (PascalCase name)
            name = m.group(1)
            if name[0].isupper():
                comp_name = name
                comp_start = i
                break

    if comp_start is None:
        return None

    # Scan forward from component start to find the function end via brace matching
    comp_end = _find_function_end(lines, comp_start)
    if comp_end is None:
        return None

    source = "\n".join(lines[comp_start : comp_end + 1])

    return {
        "component_name": comp_name,
        "source": source,
        "start_line": comp_start + 1,  # 1-indexed
        "end_line": comp_end + 1,
        "file": file,
    }


def _find_function_end(lines: list[str], start: int) -> int | None:
    """Find the closing brace of a function starting at `start`.

    Tracks brace depth, accounting for strings, template literals,
    and single-line comments.
    """
    depth = 0
    found_open = False

    for i in range(start, len(lines)):
        line = lines[i]
        j = 0
        while j < len(line):
            ch = line[j]

            # Skip single-line comments
            if ch == "/" and j + 1 < len(line) and line[j + 1] == "/":
                break

            # Skip strings
            if ch in ('"', "'", "`"):
                quote = ch
                j += 1
                while j < len(line):
                    if line[j] == "\\" and j + 1 < len(line):
                        j += 2
                        continue
                    if line[j] == quote:
                        break
                    j += 1
                j += 1
                continue

            if ch == "{":
                depth += 1
                found_open = True
            elif ch == "}":
                depth -= 1
                if found_open and depth == 0:
                    return i

            j += 1

    return None
