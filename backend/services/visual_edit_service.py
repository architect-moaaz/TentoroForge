"""Visual edit service — direct Tailwind class and text edits on .tsx files.

These are fast, non-AI edits that modify className strings and text content
directly in the source file. The running Next.js dev server picks up changes
via HMR for near-instant feedback.
"""

import re
from pathlib import Path


def _find_classname_on_or_near(lines: list[str], target_line: int, search_range: int = 3):
    """Find className="..." on or near the target line.

    Returns (line_index, match, flavor) or (None, None, None).
    flavor is "double_quote", "backtick", "cn", or "clsx".
    """
    start = max(0, target_line - 1)
    end = min(len(lines), target_line + search_range)

    for i in range(start, end):
        line = lines[i]

        # className="..."
        m = re.search(r'className="([^"]*)"', line)
        if m:
            return i, m, "double_quote"

        # className={`...`}
        m = re.search(r"className=\{`([^`]*)`\}", line)
        if m:
            return i, m, "backtick"

        # className={cn("...", ...)} — extract the first string argument
        m = re.search(r'className=\{(?:cn|clsx)\(\s*"([^"]*)"', line)
        if m:
            return i, m, "cn"

        # className={'...'}
        m = re.search(r"className=\{'([^']*)'\}", line)
        if m:
            return i, m, "single_quote"

    return None, None, None


def apply_tailwind_edit(
    output_dir: str,
    file: str,
    line: int,
    action: str,
    class_name: str,
    replace_with: str | None = None,
) -> bool:
    """Add, remove, or replace a Tailwind class on or near a specific line.

    Returns True if the file was modified.
    """
    file_path = Path(output_dir) / file
    if not file_path.exists():
        return False

    lines = file_path.read_text().split("\n")
    if line < 1 or line > len(lines):
        return False

    line_idx, class_match, flavor = _find_classname_on_or_near(lines, line)
    if line_idx is None or class_match is None:
        return False

    classes = class_match.group(1).split()

    if action == "add":
        if class_name not in classes:
            classes.append(class_name)
    elif action == "remove":
        classes = [c for c in classes if c != class_name]
    elif action == "replace":
        if replace_with:
            classes = [replace_with if c == class_name else c for c in classes]
    else:
        return False

    new_class_str = " ".join(classes)
    target_line = lines[line_idx]
    new_line = (
        target_line[: class_match.start(1)]
        + new_class_str
        + target_line[class_match.end(1) :]
    )
    lines[line_idx] = new_line
    file_path.write_text("\n".join(lines))
    return True


def apply_text_edit(
    output_dir: str,
    file: str,
    line: int,
    old_text: str,
    new_text: str,
) -> bool:
    """Replace text content on or near a specific line.

    Searches the target line and a few lines around it for the old_text,
    to handle cases where line numbers are slightly off after edits.

    Returns True if the file was modified.
    """
    file_path = Path(output_dir) / file
    if not file_path.exists():
        return False

    lines = file_path.read_text().split("\n")
    if line < 1 or line > len(lines):
        return False

    # Search target line first, then nearby lines
    search_range = 5
    start = max(0, line - 1 - search_range)
    end = min(len(lines), line + search_range)

    # Prefer exact line, then expand outward
    search_order = [line - 1]
    for offset in range(1, search_range + 1):
        if line - 1 + offset < end:
            search_order.append(line - 1 + offset)
        if line - 1 - offset >= start:
            search_order.append(line - 1 - offset)

    for i in search_order:
        if old_text in lines[i]:
            lines[i] = lines[i].replace(old_text, new_text, 1)
            file_path.write_text("\n".join(lines))
            return True

    return False


def apply_prop_edit(
    output_dir: str,
    file: str,
    line: int,
    prop_name: str,
    old_value: str,
    new_value: str,
) -> bool:
    """Edit a JSX prop value on or near a specific line.

    Searches for prop_name="old_value" or prop_name={old_value} and replaces
    the value with new_value.

    Returns True if the file was modified.
    """
    file_path = Path(output_dir) / file
    if not file_path.exists():
        return False

    lines = file_path.read_text().split("\n")
    if line < 1 or line > len(lines):
        return False

    # Search target line first, then nearby
    search_range = 5
    start = max(0, line - 1)
    end = min(len(lines), line + search_range)

    for i in range(start, end):
        target = lines[i]

        # Try string prop: prop="value"
        pattern_str = f'{prop_name}="{re.escape(old_value)}"'
        if re.search(pattern_str, target):
            lines[i] = re.sub(
                pattern_str,
                f'{prop_name}="{new_value}"',
                target,
                count=1,
            )
            file_path.write_text("\n".join(lines))
            return True

        # Try expression prop: prop={value}
        pattern_expr = f"{prop_name}={{" + re.escape(old_value) + "}"
        if re.search(pattern_expr, target):
            lines[i] = re.sub(
                pattern_expr,
                f"{prop_name}={{{new_value}}}",
                target,
                count=1,
            )
            file_path.write_text("\n".join(lines))
            return True

    return False
