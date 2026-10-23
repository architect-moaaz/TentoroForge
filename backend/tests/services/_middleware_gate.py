"""Read a written `middleware.ts` the way a request meets it.

The tests ask what a path does, not what text the file holds: is `/shop`
open to a signed-out visitor, is `/shop-admin`? A list of words in the
matcher passed every "is the word there" assertion while opening `/payroll`.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_PUBLIC = re.compile(r"const PUBLIC_ROUTES: RegExp\[\] = \[(.*?)\n\];", re.S)
_PATTERN = re.compile(r'new RegExp\(("(?:[^"\\]|\\.)*")\)')
_MATCHER = re.compile(r'matcher:\s*\[\s*("(?:[^"\\]|\\.)*")')


class Gate:
    def __init__(self, middleware: Path | str):
        path = Path(middleware)
        if path.is_dir():
            path = path / "src" / "middleware.ts"
        self.text = path.read_text("utf-8")
        block = _PUBLIC.search(self.text)
        assert block, "the middleware declares no PUBLIC_ROUTES"
        self.public = [re.compile(json.loads(s)) for s in _PATTERN.findall(block.group(1))]
        # The matcher is a path-to-regexp source; for the shape we write
        # (`/(<lookahead>.*)`) it reads as a plain regex anchored whole.
        self.matcher = re.compile("^" + json.loads(_MATCHER.search(self.text).group(1)) + "$")

    def reaches(self, path: str) -> bool:
        """Whether the middleware runs at all for `path`."""
        return bool(self.matcher.match(path))

    def is_public(self, path: str) -> bool:
        """Whether a signed-out visitor gets `path` without being sent to sign in."""
        return not self.reaches(path) or any(r.match(path) for r in self.public)


__all__ = ["Gate"]
