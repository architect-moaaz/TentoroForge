"""The two paths that serve a phone project's picture into the Editor's frame (`/phone/serve`, `/phone/live`).

They were found by `"/phone/live" in path`, so ANY route containing that text (a project named so, a query's path, a future route)
skipped the rate limit and lost X-Frame-Options (PR #28 review, 2026-10-22). Anchored: the one project route, and what is under it.
"""
from __future__ import annotations

import re

_PHONE_PICTURE = re.compile(r"^/api/projects/[^/]+/phone/(?:serve|live)(?:/|$)")


def is_phone_picture(path: str) -> bool:
    return bool(_PHONE_PICTURE.match(path))
