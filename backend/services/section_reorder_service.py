"""Section reorder service — moves JSX sections in source code.

Uses a line-based approach with brace-depth tracking to identify
and move sections within a page file.
"""

import asyncio
import json
import os
from pathlib import Path

from services.component_extractor import _find_function_end


async def reorder_section(
    output_dir: str,
    source_file: str,
    source_line: int,
    target_file: str,
    target_line: int,
    position: str,  # "before" | "after"
) -> bool:
    """Move a JSX section from source_line to before/after target_line.

    Tries the Babel AST approach first via reorder-section.mjs,
    falls back to line-based approach.

    Returns True if the file was modified.
    """
    # Try Babel script first
    script_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "static",
        "reorder-section.mjs",
    )

    if source_file == target_file and os.path.exists(script_path):
        try:
            abs_path = os.path.join(output_dir, source_file)
            proc = await asyncio.create_subprocess_exec(
                "node",
                script_path,
                abs_path,
                str(source_line),
                str(target_line),
                position,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=output_dir,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode == 0:
                result = json.loads(stdout.decode())
                return result.get("reordered", False)
        except Exception:
            pass

    # Fallback: line-based approach
    return _line_based_reorder(
        output_dir, source_file, source_line, target_line, position
    )


def _find_jsx_element_range(
    lines: list[str],
    start_line: int,
) -> tuple[int, int] | None:
    """Find the full line range of a JSX element starting at start_line.

    Uses brace/tag depth tracking to find the matching closing tag or
    self-closing end.
    """
    if start_line < 1 or start_line > len(lines):
        return None

    start_idx = start_line - 1
    line = lines[start_idx].strip()

    # Check if it's a self-closing tag on a single line
    if line.endswith("/>"):
        return (start_idx, start_idx)

    # Track angle bracket depth for JSX elements
    depth = 0
    in_string = False
    string_char = ""

    for i in range(start_idx, len(lines)):
        text = lines[i]
        j = 0
        while j < len(text):
            ch = text[j]

            # Handle strings
            if in_string:
                if ch == "\\" and j + 1 < len(text):
                    j += 2
                    continue
                if ch == string_char:
                    in_string = False
                j += 1
                continue

            if ch in ('"', "'", "`"):
                in_string = True
                string_char = ch
                j += 1
                continue

            # Skip single-line comments
            if ch == "/" and j + 1 < len(text) and text[j + 1] == "/":
                break

            if ch == "<":
                # Check if it's a closing tag
                if j + 1 < len(text) and text[j + 1] == "/":
                    depth -= 1
                    if depth <= 0:
                        # Find the > to get the end
                        end = text.find(">", j + 1)
                        if end >= 0:
                            return (start_idx, i)
                        # > might be on next line
                        for k in range(i + 1, min(len(lines), i + 3)):
                            if ">" in lines[k]:
                                return (start_idx, k)
                        return (start_idx, i)
                else:
                    depth += 1

            # Self-closing
            if ch == "/" and j + 1 < len(text) and text[j + 1] == ">":
                depth -= 1
                if depth <= 0:
                    return (start_idx, i)

            j += 1

    # Fallback: couldn't find end, use brace matching
    return None


def _line_based_reorder(
    output_dir: str,
    file: str,
    source_line: int,
    target_line: int,
    position: str,
) -> bool:
    """Reorder sections using line-based cut-and-paste."""
    filepath = Path(output_dir) / file
    if not filepath.exists():
        return False

    lines = filepath.read_text().splitlines()

    # Find the range of the source element
    source_range = _find_jsx_element_range(lines, source_line)
    if not source_range:
        return False

    source_start, source_end = source_range

    # Extract the source lines
    source_lines = lines[source_start : source_end + 1]

    # Remove source lines from the file
    remaining = lines[:source_start] + lines[source_end + 1 :]

    # Adjust target line after removal
    adjusted_target = target_line - 1  # 0-indexed
    if adjusted_target > source_start:
        adjusted_target -= (source_end - source_start + 1)

    # Find target element range in the remaining lines
    target_range = _find_jsx_element_range(remaining, adjusted_target + 1)

    if target_range:
        if position == "before":
            insert_idx = target_range[0]
        else:
            insert_idx = target_range[1] + 1
    else:
        # Fallback: insert at the adjusted target line
        if position == "before":
            insert_idx = max(0, adjusted_target)
        else:
            insert_idx = min(len(remaining), adjusted_target + 1)

    # Insert source lines at the new position
    new_lines = remaining[:insert_idx] + source_lines + remaining[insert_idx:]
    filepath.write_text("\n".join(new_lines))
    return True
