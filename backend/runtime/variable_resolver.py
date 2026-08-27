"""Variable resolver — resolves {{path.to.value}} templates in workflow data."""

import re
from typing import Any

_TEMPLATE_RE = re.compile(r"\{\{(.+?)\}\}")


class VariableResolver:
    """Resolve {{path.to.value}} templates against workflow instance variables.

    Supports paths like:
    - {{trigger.body}}
    - {{previous.output}}
    - {{n_xxx_2.output.field}}
    """

    def __init__(self, variables: dict):
        self.variables = variables

    def resolve_string(self, template: str) -> str:
        """Replace all {{path}} occurrences in a string with resolved values."""
        if "{{" not in template:
            return template

        def _replace(match: re.Match) -> str:
            path = match.group(1).strip()
            value = self._resolve_path(path)
            if value is _SENTINEL:
                return match.group(0)
            return str(value) if not isinstance(value, str) else value

        return _TEMPLATE_RE.sub(_replace, template)

    def resolve_dict(self, data: dict) -> dict:
        """Recursively resolve all string values in a dict."""
        resolved: dict = {}
        for key, value in data.items():
            resolved[key] = self._resolve_value(value)
        return resolved

    def resolve_value(self, value: Any) -> Any:
        """Resolve a single value (string, dict, list, or passthrough)."""
        return self._resolve_value(value)

    def _resolve_value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.resolve_string(value)
        if isinstance(value, dict):
            return self.resolve_dict(value)
        if isinstance(value, list):
            return [self._resolve_value(item) for item in value]
        return value

    def _resolve_path(self, path: str) -> Any:
        """Walk dot-separated path in variables dict.

        Returns the match object itself as a sentinel if the path can't be resolved,
        so the original {{...}} is preserved.
        """
        parts = path.split(".")
        current: Any = self.variables

        for part in parts:
            if isinstance(current, dict):
                if part in current:
                    current = current[part]
                else:
                    return _SENTINEL
            else:
                return _SENTINEL

        return current


# Sentinel object for "unresolvable" — using a unique object instead of None
# because None could be a valid resolved value.
_SENTINEL = object()
