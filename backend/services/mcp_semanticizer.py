"""MCP Code Semanticizer — converts Figma MCP visual code to semantic HTML/JSX.

The Figma MCP outputs pixel-perfect visual code where everything is <div>/<p>
with styles. This module recognizes patterns from Figma layer names (data-name)
and converts them to proper semantic elements:

  - data-name="Button" → <button>
  - data-name="Text Input" / "Email Input" → <input>
  - data-name="Primitive.button" (dropdowns) → <select> or clickable div
  - data-name="Form" → <form>
  - data-name="Checkbox" → <input type="checkbox">
  - data-name="Icon" → keep as-is (image)
  - data-name containing "Link" → <a> or clickable
"""

import re
import logging

logger = logging.getLogger(__name__)


def semanticize_mcp_code(code: str) -> str:
    """Convert Figma MCP visual code to semantic React/TSX.

    Uses a tag-replacement approach: changes <div to <button, <input, etc.
    based on data-name attributes, and fixes corresponding closing tags.
    """
    result = code

    # 1. Buttons: <div ... data-name="Button" ...> → <button ... >
    #    and their closing </div> → </button>
    result = _replace_tag_by_name(result, "Button", "button")

    # 2. Text inputs: convert entire element to <input />
    result = _convert_named_inputs(result, "Text Input", "text")
    result = _convert_named_inputs(result, "Email Input", "email")
    result = _convert_named_inputs(result, "Password Input", "password")

    # 3. Dropdowns
    result = _replace_tag_by_name(result, "Primitive.button", "select")

    # 4. Checkboxes
    result = _convert_checkboxes(result)

    # 5. Forms
    result = _replace_tag_by_name(result, "Form", "form")
    result = _replace_tag_by_name(result, "Sign in Form", "form")

    # 6. Links
    result = _replace_tag_by_name(result, "Link", "a")

    # 7. Labels
    result = _replace_tag_by_name(result, "Primitive.label", "label")

    # 8. Clean up data-name and data-node-id attributes
    result = re.sub(r'\s*data-name="[^"]*"', '', result)
    result = re.sub(r'\s*data-node-id="[^"]*"', '', result)

    return result


def _replace_tag_by_name(code: str, data_name: str, new_tag: str) -> str:
    """Replace <div data-name="X" ...> with <new_tag ...> and fix closing tags.

    Uses a stack-based approach to find matching closing </div> tags.
    """
    escaped_name = re.escape(data_name)
    # Find all opening tags with this data-name
    pattern = rf'<div([^>]*data-name="{escaped_name}"[^>]*)>'

    # Process each match from end to start (so indices don't shift)
    matches = list(re.finditer(pattern, code))
    for match in reversed(matches):
        start = match.start()
        attrs = match.group(1).replace(f'data-name="{data_name}"', '').strip()

        # Find the matching closing </div> using a stack
        depth = 1
        pos = match.end()
        while depth > 0 and pos < len(code):
            next_open = code.find('<div', pos)
            next_close = code.find('</div>', pos)

            if next_close == -1:
                break

            if next_open != -1 and next_open < next_close:
                depth += 1
                pos = next_open + 4
            else:
                depth -= 1
                if depth == 0:
                    # Replace closing tag
                    code = code[:next_close] + f'</{new_tag}>' + code[next_close + 6:]
                else:
                    pos = next_close + 6

        # Replace opening tag
        code = code[:start] + f'<{new_tag}{attrs}>' + code[match.end():]

    return code


def _convert_named_inputs(code: str, data_name: str, input_type: str) -> str:
    """Convert div-based inputs to <input> elements.

    Finds elements with the given data-name, extracts className and
    placeholder text, replaces the entire element with <input />.
    """
    escaped_name = re.escape(data_name)
    pattern = rf'<div([^>]*data-name="{escaped_name}"[^>]*)>([\s\S]*?)</div>'

    def make_input(match: re.Match) -> str:
        attrs = match.group(1)
        inner = match.group(2)

        # Extract className
        class_match = re.search(r'className="([^"]*)"', attrs)
        classes = class_match.group(1) if class_match else ""

        # Extract placeholder text from inner content
        text_match = re.search(r'>([^<]+)</', inner)
        placeholder = text_match.group(1).strip() if text_match else ""

        return f'<input type="{input_type}" className="{classes}" placeholder="{placeholder}" />'

    code = re.sub(pattern, make_input, code)
    return code


def _convert_checkboxes(code: str) -> str:
    """Convert div-based checkboxes to <input type="checkbox">."""
    pattern = r'<div([^>]*data-name="Checkbox"[^>]*)(?:\s*/\s*>|>([\s\S]*?)</div>)'

    def replace_checkbox(match: re.Match) -> str:
        attrs = match.group(1)
        class_match = re.search(r'className="([^"]*)"', attrs)
        classes = class_match.group(1) if class_match else ""
        return f'<input type="checkbox" className="{classes}" />'

    code = re.sub(pattern, replace_checkbox, code)
    return code
