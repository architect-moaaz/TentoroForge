"""What a user actually pastes (PRD §41).

§41 says the user supplies a *Figma design URL*. It does not say the user
supplies a file key and a node id, and that distinction is the whole reason
this module exists: a design URL is a human artifact with five shapes, and the
MCP wants two identifiers.

The shapes seen in the wild::

    figma.com/design/<fileKey>/<slug>?node-id=1-234
    figma.com/file/<fileKey>/<slug>?node-id=1%3A234       # older, still issued
    figma.com/design/<fileKey>/branch/<branchKey>/<slug>  # a branch
    figma.com/design/<fileKey>/<slug>                     # whole file, no frame
    figma.com/proto/<fileKey>/<slug>?node-id=1-234        # a prototype link

Two decisions worth stating.

**The node id is optional.** The legacy parser returned ``None`` without one,
which quietly turned "user pasted a link to the whole file" into "the Figma
step is unavailable". A link with no ``node-id`` is not malformed — it names
the entire file, which is the common case when someone copies the URL from the
browser bar rather than right-clicking a frame. §44 wants the file's pages and
frames anyway, so the file *is* a legitimate target.

**A branch is a different file.** Figma branches have their own file key and
the API resolves them independently. Treating a branch URL as its parent would
extract the wrong design and never say so, so the branch key wins when present.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlparse


#: ``/design/<key>``, ``/file/<key>``, ``/proto/<key>``. Figma file keys are
#: alphanumeric; the slug that follows is decorative and never parsed.
_FILE = re.compile(r"/(?:design|file|proto|board)/([A-Za-z0-9]{10,})", re.I)

#: ``/branch/<key>`` appears *after* the parent file key when a branch is open.
_BRANCH = re.compile(r"/branch/([A-Za-z0-9]{10,})", re.I)


@dataclass(frozen=True)
class FigmaTarget:
    """The two identifiers the MCP needs, plus where they came from.

    ``node_id`` is ``None`` when the URL names the whole file. Callers must
    handle that rather than defaulting to a root node id — "the whole file"
    and "the node that happens to be at 0:1" are different extractions.
    """

    file_key: str
    node_id: str | None = None
    #: Present only for branch URLs. When set, :attr:`file_key` is already the
    #: branch's own key — this is retained for provenance, not for fetching.
    parent_file_key: str | None = None
    source_url: str = ""
    #: Which tool the identifiers belong to. ``figma`` (file key + node id) or
    #: ``uxpilot`` (``file_key`` is the page id). Display only: the store and
    #: the reference carry the same two identifiers for either.
    kind: str = "figma"

    @property
    def is_whole_file(self) -> bool:
        return self.node_id is None

    def describe(self) -> str:
        """Human-readable, for clarification questions and run logs."""
        if self.kind == "uxpilot":
            return f"UX Pilot page {self.file_key}"
        where = f"node {self.node_id}" if self.node_id else "the whole file"
        branch = f" (branch of {self.parent_file_key})" if self.parent_file_key else ""
        return f"{self.file_key}{branch}, {where}"


def normalise_node_id(raw: str) -> str:
    """``1-234`` → ``1:234``.

    Figma writes node ids with a hyphen in URLs and a colon in the API. The
    URL form may also arrive percent-encoded (``1%3A234``) when it was copied
    out of another tool, so unquote before substituting.
    """
    return unquote(raw).strip().replace("-", ":")


def parse(url: str) -> FigmaTarget | None:
    """Parse a Figma URL into a target, or ``None`` if it is not one.

    Returning ``None`` rather than raising: this is called on text a user
    typed, and "that does not look like a Figma link" is a conversation turn
    (§16), not an exception.
    """
    if not url or not url.strip():
        return None

    text = url.strip()
    # Tolerate a bare ``figma.com/...`` paste with no scheme; urlparse would
    # otherwise read the host as a path segment and the host check would fail.
    if not re.match(r"^[a-z][a-z0-9+.-]*://", text, re.I):
        text = f"https://{text}"

    parsed = urlparse(text)
    if "figma.com" not in (parsed.netloc or "").lower():
        return None

    file_match = _FILE.search(parsed.path)
    if not file_match:
        return None
    file_key = file_match.group(1)

    parent: str | None = None
    branch_match = _BRANCH.search(parsed.path)
    if branch_match:
        # The branch is the file we extract from; the parent is provenance.
        parent, file_key = file_key, branch_match.group(1)

    node_id: str | None = None
    values = parse_qs(parsed.query).get("node-id") or []
    if values and values[0].strip():
        node_id = normalise_node_id(values[0])

    return FigmaTarget(
        file_key=file_key,
        node_id=node_id,
        parent_file_key=parent,
        source_url=url.strip(),
    )
