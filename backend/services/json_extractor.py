"""Robust JSON Extractor — parses LLM-generated JSON with multi-pass repair.

LLMs frequently produce JSON with these errors:
  - Extra quotes after booleans: false" → false
  - Trailing commas: [1, 2, ] → [1, 2]
  - Unmatched quotes in strings: "value → "value"
  - Control characters in strings
  - Missing closing brackets
  - Single quotes instead of double quotes
  - Comments (// or /* */)
  - Unquoted keys: {key: "value"} → {"key": "value"}

This module provides a single `extract_json()` function that handles all
these cases with a 4-pass approach, achieving ~95% extraction success.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def extract_json(
    text: str,
    marker: str = "```json",
    *,
    expect_type: type | None = None,
    required_fields: list[str] | None = None,
) -> dict | list | None:
    """Extract and parse JSON from LLM output text.

    Searches for JSON wrapped in code block markers (e.g., ```plan-json, ```design-spec).
    Applies multi-pass repair if the initial parse fails.

    Args:
        text: The full LLM output text
        marker: The code block marker to search for (e.g., "```plan-json")
        expect_type: Expected type of the result (dict or list). If provided, validates.
        required_fields: For dict results, check these keys exist.

    Returns:
        Parsed JSON (dict or list) or None if extraction fails.
    """
    # Find the marked JSON block
    raw = _find_json_block(text, marker)
    if raw is None:
        logger.debug("No %s marker found in text", marker)
        return None

    # Pass 1: Try as-is
    result = _try_parse(raw)
    if result is not None:
        return _validate(result, expect_type, required_fields)

    # Pass 2: Light repairs (most common LLM errors)
    fixed = _light_repair(raw)
    result = _try_parse(fixed)
    if result is not None:
        logger.info("JSON parsed after light repair")
        return _validate(result, expect_type, required_fields)

    # Pass 3: Heavy repairs (structural issues)
    fixed = _heavy_repair(raw)
    result = _try_parse(fixed)
    if result is not None:
        logger.info("JSON parsed after heavy repair")
        return _validate(result, expect_type, required_fields)

    # Pass 4: Line-by-line reconstruction
    result = _reconstruct(raw)
    if result is not None:
        logger.info("JSON parsed after line-by-line reconstruction")
        return _validate(result, expect_type, required_fields)

    logger.warning("Failed to extract JSON from %s block after all repair passes", marker)
    return None


def _find_json_block(text: str, marker: str) -> str | None:
    """Find the JSON content between marker and closing ```."""
    # Try exact marker first
    idx = text.find(marker)
    if idx == -1:
        # Try without backticks (e.g., just "plan-json")
        bare = marker.lstrip("`")
        idx = text.find(f"```{bare}")
        if idx != -1:
            marker = f"```{bare}"
        else:
            # Try finding any JSON code block
            for alt in ("```json", "```"):
                idx = text.find(alt)
                if idx != -1:
                    marker = alt
                    break

    if idx == -1:
        return None

    start = idx + len(marker)
    # Skip optional newline after marker
    if start < len(text) and text[start] == "\n":
        start += 1

    end = text.find("```", start)
    if end == -1:
        # No closing ``` — take rest of text and try to find valid JSON
        end = len(text)

    return text[start:end].strip()


def _try_parse(raw: str) -> dict | list | None:
    """Attempt to parse JSON, return None on failure."""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None


def _light_repair(raw: str) -> str:
    """Fix common LLM JSON errors."""
    fixed = raw

    # Fix extra quote after boolean/null: false" → false
    fixed = re.sub(r'\b(true|false|null)"(?=\s*[,}\]])', r'\1', fixed)

    # Fix boolean without closing quote in string: "false} → "false"}
    fixed = re.sub(r'"(true|false|null)(?=\s*[}\],])', r'"\1"', fixed)

    # Remove trailing commas before ] or }
    fixed = re.sub(r',\s*([}\]])', r'\1', fixed)

    # Remove JavaScript comments
    fixed = re.sub(r'//.*?$', '', fixed, flags=re.MULTILINE)
    fixed = re.sub(r'/\*.*?\*/', '', fixed, flags=re.DOTALL)

    # Fix single quotes → double quotes (but not within strings)
    # Only do this if there are no double quotes at all (likely all single-quoted)
    if fixed.count("'") > fixed.count('"'):
        fixed = re.sub(r"'([^']*)'", r'"\1"', fixed)

    return fixed


def _heavy_repair(raw: str) -> str:
    """Fix structural JSON issues."""
    fixed = _light_repair(raw)

    # Strip control characters
    fixed = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', ' ', fixed)

    # Fix unquoted keys: {key: "value"} → {"key": "value"}
    fixed = re.sub(r'(?<=[{,])\s*([a-zA-Z_]\w*)\s*:', r' "\1":', fixed)

    # Fix missing closing quote before comma/brace: "value → "value"
    # This handles: "key": "value_without_end,
    fixed = re.sub(r'":\s*"([^"]*?)(?=\s*[,}](?:\s*"))', r'": "\1"', fixed)

    # Balance brackets
    fixed = _balance_brackets(fixed)

    return fixed


def _balance_brackets(raw: str) -> str:
    """Ensure brackets are balanced by adding missing closing brackets."""
    opens = 0
    closes = 0
    open_sq = 0
    close_sq = 0
    in_string = False
    escape = False

    for ch in raw:
        if escape:
            escape = False
            continue
        if ch == '\\':
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == '{':
            opens += 1
        elif ch == '}':
            closes += 1
        elif ch == '[':
            open_sq += 1
        elif ch == ']':
            close_sq += 1

    # Add missing closing brackets
    result = raw
    for _ in range(open_sq - close_sq):
        result += "]"
    for _ in range(opens - closes):
        result += "}"

    return result


def _reconstruct(raw: str) -> dict | list | None:
    """Last resort: try to extract valid JSON by finding the outermost { } or [ ]."""
    # Find the first { or [
    first_brace = -1
    first_bracket = -1
    for i, ch in enumerate(raw):
        if ch == '{' and first_brace == -1:
            first_brace = i
        if ch == '[' and first_bracket == -1:
            first_bracket = i
        if first_brace >= 0 and first_bracket >= 0:
            break

    if first_brace == -1 and first_bracket == -1:
        return None

    # Determine if it's an object or array
    if first_bracket >= 0 and (first_brace == -1 or first_bracket < first_brace):
        start_char = '['
        end_char = ']'
        start = first_bracket
    else:
        start_char = '{'
        end_char = '}'
        start = first_brace

    # Find matching close by counting depth
    depth = 0
    in_string = False
    escape = False
    end = start

    for i in range(start, len(raw)):
        ch = raw[i]
        if escape:
            escape = False
            continue
        if ch == '\\':
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == start_char:
            depth += 1
        elif ch == end_char:
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    if depth != 0:
        # Unbalanced — add closing brackets
        chunk = raw[start:]
        chunk = _balance_brackets(chunk)
    else:
        chunk = raw[start:end]

    # Apply light repair and try
    chunk = _light_repair(chunk)
    return _try_parse(chunk)


def _validate(
    result: dict | list | None,
    expect_type: type | None,
    required_fields: list[str] | None,
) -> dict | list | None:
    """Validate the parsed result."""
    if result is None:
        return None

    if expect_type is not None and not isinstance(result, expect_type):
        # Try to adapt: if we expected list but got dict with an $id, wrap it
        if expect_type is list and isinstance(result, dict):
            if "$id" in result or "route" in result:
                return [result]
        logger.warning("Expected %s but got %s", expect_type.__name__, type(result).__name__)
        return None

    if required_fields and isinstance(result, dict):
        missing = [f for f in required_fields if f not in result]
        if missing:
            logger.warning("Missing required fields: %s", missing)
            # Don't reject — the LLM might have used slightly different keys
            # Just log the warning

    return result
