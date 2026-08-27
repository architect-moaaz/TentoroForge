"""Extract JSX element props for the context panel.

Reads a .tsx file at a given line and extracts JSX attributes,
className classes, text content, and component name.
"""

import re
from pathlib import Path


def extract_element_props(
    output_dir: str,
    file: str,
    line: int,
) -> dict | None:
    """Extract JSX element properties at a given line.

    Returns:
        {
            "props": { "prop_name": "value", ... },
            "classes": ["class1", "class2", ...],
            "component_name": "ComponentName" | null,
            "text_content": "text" | null,
            "self_closing": bool,
        }

    Returns None if the file/line is invalid.
    """
    filepath = Path(output_dir) / file
    if not filepath.exists():
        return None

    try:
        lines = filepath.read_text().splitlines()
    except Exception:
        return None

    if line < 1 or line > len(lines):
        return None

    target = lines[line - 1]

    # Find the JSX opening tag on or near this line
    # Collect the full tag by scanning forward until we find > or />
    tag_lines = []
    start_idx = line - 1

    # Scan up to 10 lines for the complete tag
    for i in range(start_idx, min(len(lines), start_idx + 10)):
        tag_lines.append(lines[i])
        joined = "\n".join(tag_lines)
        if re.search(r"/?>", joined):
            break

    tag_source = "\n".join(tag_lines)

    # Extract tag name
    tag_match = re.match(r"\s*<(\w+(?:\.\w+)*)", target)
    if not tag_match:
        # Try the standard pattern for JSX
        tag_match = re.search(r"<(\w+(?:\.\w+)*)", target)

    component_name = None
    if tag_match:
        name = tag_match.group(1)
        # PascalCase = component
        if name[0].isupper():
            component_name = name

    # Check self-closing
    self_closing = bool(re.search(r"/>\s*$", tag_source.strip()))

    # Extract props (simple regex approach)
    props: dict[str, str] = {}

    # String props: prop="value"
    for m in re.finditer(r'(\w+)="([^"]*)"', tag_source):
        prop_name = m.group(1)
        if prop_name.startswith("data-source-"):
            continue  # Skip bridge annotations
        props[prop_name] = m.group(2)

    # Expression props: prop={value} (simple single-line)
    for m in re.finditer(r"(\w+)=\{([^}]+)\}", tag_source):
        prop_name = m.group(1)
        if prop_name.startswith("data-source-"):
            continue
        if prop_name not in props:  # don't override string matches
            props[prop_name] = m.group(2).strip()

    # Boolean props: just the prop name
    for m in re.finditer(r"\s(\w+)(?=\s|/?>)", tag_source):
        prop_name = m.group(1)
        if prop_name not in props and prop_name[0].islower():
            # Only include if it looks like a boolean prop (not a tag)
            if not re.match(r"^(className|style|id|key|ref|onClick|onChange|onSubmit)$", prop_name):
                props[prop_name] = "true"

    # Extract classes from className
    classes: list[str] = []
    class_value = props.pop("className", None)
    if class_value:
        classes = [c for c in class_value.split() if c]

    # Extract text content (look at lines after the opening tag)
    text_content = None
    if not self_closing:
        tag_end_line = start_idx + len(tag_lines) - 1
        # Look at the next few lines for text content
        for i in range(tag_end_line, min(len(lines), tag_end_line + 3)):
            content = lines[i].strip()
            # Remove JSX tags
            content = re.sub(r"<[^>]+>", "", content).strip()
            if content and not content.startswith("{") and not content.startswith("//"):
                text_content = content[:100]
                break

    return {
        "props": props,
        "classes": classes,
        "component_name": component_name,
        "text_content": text_content,
        "self_closing": self_closing,
    }
