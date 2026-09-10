"""
Auto-repair simple registry mismatches in generated code.

Handles cases where the fix is deterministic (wrong case, trailing slash, etc.)
without needing an LLM. Returns list of files modified.
"""

import re
import logging
from pathlib import Path
from services.registry_validator import RegistryError

logger = logging.getLogger(__name__)


def auto_fix_mismatches(output_dir: str, errors: list[RegistryError]) -> list[str]:
    """Attempt to auto-fix deterministic mismatches. Returns list of files modified."""
    root = Path(output_dir)
    modified: list[str] = []

    for err in errors:
        if err.suggestion and err.section == "pages" and "imports unregistered component" in err.error:
            # Try to fix component import name
            fixed = _fix_component_import(root, err)
            if fixed:
                modified.append(fixed)
        elif err.suggestion and err.section == "components" and "references non-existent field" in err.error:
            # Try to fix field reference in component
            fixed = _fix_field_reference(root, err)
            if fixed:
                modified.append(fixed)

    if modified:
        logger.info("Auto-fixed %d file(s): %s", len(modified), modified)
    return list(set(modified))


def _fix_component_import(root: Path, err: RegistryError) -> str | None:
    """Fix a page importing a component with wrong name."""
    # err.name is the page route like "/orders"
    # err.error is like "Page imports unregistered component 'OrdersList'"
    # err.suggestion is like "Did you mean 'OrdersTable'?"

    # Extract the wrong name and suggestion
    wrong_match = re.search(r"'(\w+)'", err.error)
    right_match = re.search(r"'(\w+)'", err.suggestion) if err.suggestion else None
    if not wrong_match or not right_match:
        return None

    wrong_name = wrong_match.group(1)
    right_name = right_match.group(1)

    # Find all page.tsx files and fix the import
    for page_file in root.rglob("page.tsx"):
        if "node_modules" in str(page_file):
            continue
        try:
            content = page_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        if wrong_name in content:
            new_content = content.replace(wrong_name, right_name)
            if new_content != content:
                page_file.write_text(new_content, encoding="utf-8")
                logger.info("Fixed import %s -> %s in %s", wrong_name, right_name, page_file)
                return str(page_file.relative_to(root))

    return None


def _fix_field_reference(root: Path, err: RegistryError) -> str | None:
    """Fix a component referencing a field with wrong name."""
    # err.name is the component name like "OrderTable"
    # err.error like "Field ref 'Order.fullName' references non-existent field 'fullName' on entity 'Order'"
    # err.suggestion like "Did you mean 'name'?"

    wrong_field_match = re.search(r"non-existent field '(\w+)'", err.error)
    right_match = re.search(r"'(\w+)'", err.suggestion) if err.suggestion else None
    if not wrong_field_match or not right_match:
        return None

    wrong_field = wrong_field_match.group(1)
    right_field = right_match.group(1)

    # Find the component file
    for tsx_file in root.rglob("*.tsx"):
        if "node_modules" in str(tsx_file):
            continue
        try:
            content = tsx_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        # Only fix in files that export the component
        if f"function {err.name}" not in content and f"const {err.name}" not in content:
            continue

        # Replace field references like .fullName or ["fullName"] or item.fullName
        # Be careful to only replace in JSX/data contexts, not in unrelated strings
        patterns = [
            (f'.{wrong_field}', f'.{right_field}'),
            (f'"{wrong_field}"', f'"{right_field}"'),
            (f"'{wrong_field}'", f"'{right_field}'"),
        ]
        new_content = content
        for old, new in patterns:
            new_content = new_content.replace(old, new)

        if new_content != content:
            tsx_file.write_text(new_content, encoding="utf-8")
            logger.info("Fixed field ref %s -> %s in %s", wrong_field, right_field, tsx_file)
            return str(tsx_file.relative_to(root))

    return None
