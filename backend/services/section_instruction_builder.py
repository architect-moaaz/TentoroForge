"""Instruction builder for AI section generation.

Builds a detailed instruction for the code_editor agent when adding
a new section to a page. Spec D Wave 6 — the section-kind pool now
comes from :mod:`services.section_authoring`; the old 15-item
``section_templates`` catalog is retired.
"""

import json
from pathlib import Path

from services.section_authoring import author_section


def _load_brief(output_dir: str) -> dict | None:
    """Best-effort read of ``contracts/brief.json`` as a plain dict.

    Returns ``None`` on missing file / malformed JSON — the authoring
    pass falls back to a palette-agnostic recipe."""
    path = Path(output_dir) / "contracts" / "brief.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def build_section_instruction(
    output_dir: str,
    page_file: str,
    template_id: str | None = None,
    custom_prompt: str | None = None,
    insert_position: str = "end",
) -> str:
    """Build a detailed instruction for section generation.

    Args:
        output_dir: Project output directory.
        page_file: Relative path to the page file (e.g., "src/app/page.tsx").
        template_id: Section kind id from the authoring catalog (optional).
        custom_prompt: Freeform user description (optional).
        insert_position: Where to insert — "end", "start", or "after:{xpath}".

    Returns:
        Instruction string for the code_editor agent.
    """
    # Read existing page source
    filepath = Path(output_dir) / page_file
    page_source = ""
    if filepath.exists():
        page_source = filepath.read_text()

    # Author the section description
    if template_id:
        brief = _load_brief(output_dir)
        page_context = {"file": page_file, "source_preview": page_source[:1000]}
        recipe = author_section(template_id, page_context=page_context, brief=brief)
        section_desc = recipe["prompt"]
    elif custom_prompt:
        section_desc = custom_prompt
    else:
        section_desc = "Add a new section"

    # Determine insert location instruction
    if insert_position == "start":
        position_desc = "Insert the new section at the BEGINNING of the page content (after any imports/declarations, as the first JSX child)."
    elif insert_position.startswith("after:"):
        position_desc = f"Insert the new section after the element at position: {insert_position[6:]}"
    else:
        position_desc = "Insert the new section at the END of the page content (as the last JSX child before the closing tag)."

    # Build instruction
    parts = [
        f"## Task: Add a new section to the page",
        f"",
        f"### Section to add:",
        section_desc,
        f"",
        f"### Placement:",
        position_desc,
        f"",
        f"### Target file: {page_file}",
        f"",
        f"### Requirements:",
        f"- Use Tailwind CSS for all styling",
        f"- Make the section responsive (mobile-first)",
        f"- Use semantic HTML elements (section, header, footer, etc.)",
        f"- Match the existing design patterns and color scheme from the page",
        f"- Use placeholder content (lorem ipsum, sample data) where appropriate",
        f"- Do NOT import any external libraries — only use what's already imported",
        f"- Keep the new code within the existing component's return statement",
        f"",
        f"### Current page source:",
        f"```tsx",
        page_source[:3000] if page_source else "// Empty page",
        f"```",
    ]

    return "\n".join(parts)
