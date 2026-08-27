"""Stable Blueprint ID allocation (PRD §12, §116).

Why this exists
---------------
§12 says every significant Blueprint object has an ID. §116 says the
deterministic layer — not the model — owns them. The reason is §92 and §21:
change history follows an artifact across revisions, and ``codeMap`` answers
"which files implement REQ-017". Both break the moment an ID moves.

So the hard requirement is not *generating* IDs. It is **re-generating the same
ID for the same artifact on the next run**. If the planner re-proposes the
``Candidate`` entity tomorrow it must come back as ``ENTITY-001``, not
``ENTITY-007``, or every downstream reference silently retargets.

That means an allocator cannot be a counter. It is a registry keyed by an
artifact's *natural identity* — the thing about the artifact that survives
rewording:

    ENTITY   entity name              (names are the identity)
    PAGE     route                    (titles get reworded; routes don't)
    API      method + path
    ROLE     role name
    PERM     subject + action
    MODULE   module name
    CMP      component name
    FLOW     workflow name
    REQ      normalised prose digest  ← see below
    RULE     normalised prose digest
    DEC      normalised prose digest

Prose artifacts are the awkward case: a requirement that gets reworded is
usually still the *same* requirement, but its digest changes. Deciding whether
two phrasings mean the same thing is a judgement, and §116 puts judgement in
the model. So the split is:

    Smith decides two phrasings are the same artifact   →  ``rebind()``
    This service decides what number that artifact has  →  ``allocate()``

The allocator never guesses at sameness and never renumbers on its own.

Guarantees
----------
* **Idempotent** — ``allocate`` with a seen natural key returns the same ID.
* **Monotonic** — counters never rewind. A retired ID is never handed out
  again, so a stale reference can never silently resolve to a new artifact.
* **Immutable** — an artifact's ID does not change when it is renamed,
  deprecated (§22) or restored.
* **Concurrency-safe** — §28 permits agents to run in parallel; allocation is
  guarded by an in-process lock and a cross-process file lock.

The prefix list is mirrored from ``packages/schema/src/blueprint/ids.ts``.
``tests/services/test_blueprint_ids.py`` fails if the two drift.
"""
from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

try:  # POSIX only; the allocator degrades to in-process locking without it.
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Prefixes — mirror of ID_PREFIXES in packages/schema/src/blueprint/ids.ts
# ---------------------------------------------------------------------------

ID_PREFIXES: tuple[str, ...] = (
    "REQ",
    "ROLE",
    "PERM",
    "MODULE",
    "PAGE",
    "CMP",
    "ENTITY",
    "FLOW",
    "RULE",
    "API",
    "TEST",
    "DEC",
    "INT",
    "DEP",
    "WIDGET",
)

_ID_RE = re.compile(rf"^({'|'.join(ID_PREFIXES)})-(\d{{3,}})$")

#: Width IDs are zero-padded to. Beyond 999 they simply grow (REQ-1000), which
#: the ``\d{3,}`` contract on both sides already admits.
_PAD = 3


class UnknownPrefix(ValueError):
    """Raised when allocation is attempted for a prefix outside §12."""


class InvalidArtifactId(ValueError):
    """Raised when a string that should be an artifact ID is malformed."""


def parse_id(artifact_id: str) -> tuple[str, int]:
    """Split ``"ENTITY-001"`` into ``("ENTITY", 1)``.

    Raises :class:`InvalidArtifactId` rather than returning None — a malformed
    ID is a programming error, not a value to branch on.
    """
    m = _ID_RE.match(artifact_id or "")
    if not m:
        raise InvalidArtifactId(f"not a Blueprint artifact id: {artifact_id!r}")
    return m.group(1), int(m.group(2))


def is_valid_id(artifact_id: str) -> bool:
    """True when ``artifact_id`` matches the §12 format."""
    return bool(_ID_RE.match(artifact_id or ""))


# ---------------------------------------------------------------------------
# Natural keys
# ---------------------------------------------------------------------------

def _norm(text: str) -> str:
    """Casefold and collapse whitespace/punctuation so trivial edits don't
    read as a different artifact. ``"Candidate "`` and ``"candidate"`` are the
    same entity; ``"Candidates"`` deliberately is not — pluralisation is a real
    modelling difference and should surface, not be silently absorbed."""
    return re.sub(r"[\s_\-]+", " ", (text or "").strip()).casefold()


def entity_key(name: str) -> str:
    return f"ENTITY:{_norm(name)}"


def page_key(route: str) -> str:
    """Routes, not titles. A page renamed from "Candidates" to "Talent Pool"
    at ``/candidates`` is the same page; a new route is a new page."""
    r = (route or "").strip()
    if not r.startswith("/"):
        r = "/" + r
    return f"PAGE:{r.rstrip('/').casefold() or '/'}"


def api_key(method: str, path: str) -> str:
    p = (path or "").strip()
    if not p.startswith("/"):
        p = "/" + p
    return f"API:{(method or 'GET').strip().upper()} {p.rstrip('/').casefold() or '/'}"


def role_key(name: str) -> str:
    return f"ROLE:{_norm(name)}"


def permission_key(subject: str, action: str) -> str:
    return f"PERM:{_norm(subject)}:{_norm(action)}"


def module_key(name: str) -> str:
    return f"MODULE:{_norm(name)}"


def component_key(name: str) -> str:
    return f"CMP:{_norm(name)}"


def workflow_key(name: str) -> str:
    return f"FLOW:{_norm(name)}"


def widget_key(page_route: str, label: str) -> str:
    """A widget is identified by where it sits and what it claims to show.
    Rebinding it to a different metric keeps its identity; moving it to another
    page makes it a different widget."""
    return f"WIDGET:{page_key(page_route)}:{_norm(label)}"


def prose_key(prefix: str, text: str) -> str:
    """Digest key for artifacts whose identity is prose (REQ / RULE / DEC).

    Deliberately *not* fuzzy. A reworded requirement produces a different key
    and would allocate a new ID — which is correct default behaviour, because
    the alternative is silently merging two distinct requirements. When Smith
    judges that a rewording is the same requirement, it calls
    :meth:`IdAllocator.rebind` to carry the ID across.
    """
    digest = hashlib.sha256(_norm(text).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"


# ---------------------------------------------------------------------------
# Allocator
# ---------------------------------------------------------------------------

@dataclass
class IdAllocator:
    """Per-application registry of allocated Blueprint IDs.

    Persisted next to the Blueprint at ``<output_dir>/.forge/ids.json`` so it
    travels with the application and survives process restarts.
    """

    #: prefix -> highest number handed out so far
    counters: dict[str, int] = field(default_factory=dict)
    #: natural key -> artifact id
    bindings: dict[str, str] = field(default_factory=dict)
    #: ids whose artifact is gone; never re-issued (§22 DEPRECATED, not deleted)
    retired: set[str] = field(default_factory=set)

    _output_dir: str | None = field(default=None, repr=False, compare=False)
    _lock: threading.Lock = field(
        default_factory=threading.Lock, repr=False, compare=False
    )

    # -- persistence --------------------------------------------------------

    @staticmethod
    def path_for(output_dir: str | Path) -> Path:
        return Path(output_dir) / ".forge" / "ids.json"

    @classmethod
    def load(cls, *, output_dir: str | Path) -> "IdAllocator":
        p = cls.path_for(output_dir)
        if not p.exists():
            return cls(_output_dir=str(output_dir))
        try:
            raw = json.loads(p.read_text("utf-8"))
        except (json.JSONDecodeError, OSError):
            # A corrupt registry must not silently reset to zero — that would
            # renumber every artifact in the application.
            raise InvalidArtifactId(f"id registry unreadable: {p}")
        return cls(
            counters={str(k): int(v) for k, v in (raw.get("counters") or {}).items()},
            bindings={str(k): str(v) for k, v in (raw.get("bindings") or {}).items()},
            retired=set(raw.get("retired") or []),
            _output_dir=str(output_dir),
        )

    def save(self) -> Path:
        if not self._output_dir:
            raise RuntimeError("IdAllocator has no output_dir; construct via load()")
        p = self.path_for(self._output_dir)
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "counters": dict(sorted(self.counters.items())),
            "bindings": dict(sorted(self.bindings.items())),
            "retired": sorted(self.retired),
        }
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), "utf-8")
        os.replace(tmp, p)  # atomic
        return p

    @classmethod
    @contextmanager
    def session(cls, *, output_dir: str | Path) -> Iterator["IdAllocator"]:
        """Load, allocate, save — under a cross-process lock.

        Parallel agents (§28) may allocate concurrently; without this two
        agents both read counter N and both mint the same ID.
        """
        lock_path = cls.path_for(output_dir).with_suffix(".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(lock_path, "a+")
        try:
            if fcntl is not None:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            alloc = cls.load(output_dir=output_dir)
            yield alloc
            alloc.save()
        finally:
            try:
                if fcntl is not None:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            except OSError as exc:  # pragma: no cover
                if exc.errno != errno.EBADF:
                    raise
            fh.close()

    # -- allocation ---------------------------------------------------------

    def allocate(self, prefix: str, natural_key: str) -> str:
        """Return the ID for ``natural_key``, minting one on first sight.

        Idempotent: the same natural key always yields the same ID, which is
        what makes re-generation non-destructive.
        """
        prefix = (prefix or "").strip().upper()
        if prefix not in ID_PREFIXES:
            raise UnknownPrefix(
                f"{prefix!r} is not a Blueprint prefix; expected one of "
                f"{', '.join(ID_PREFIXES)}"
            )
        if not natural_key:
            raise ValueError("natural_key is required — anonymous allocation "
                             "would renumber on every run")

        with self._lock:
            existing = self.bindings.get(natural_key)
            if existing:
                # Restoring a deprecated artifact reuses its own ID (§22).
                self.retired.discard(existing)
                return existing

            nxt = self.counters.get(prefix, 0) + 1
            self.counters[prefix] = nxt
            artifact_id = f"{prefix}-{nxt:0{_PAD}d}"
            self.bindings[natural_key] = artifact_id
            return artifact_id

    def bind(self, natural_key: str, artifact_id: str) -> None:
        """Record an ID that was allocated elsewhere (import, migration).

        Advances the counter so the imported ID can never be re-minted.
        """
        prefix, num = parse_id(artifact_id)
        with self._lock:
            clash = self.bindings.get(natural_key)
            if clash and clash != artifact_id:
                raise InvalidArtifactId(
                    f"{natural_key!r} is already bound to {clash}; use rebind()"
                )
            self.bindings[natural_key] = artifact_id
            self.counters[prefix] = max(self.counters.get(prefix, 0), num)
            self.retired.discard(artifact_id)

    def rebind(self, *, old_key: str, new_key: str) -> str:
        """Carry an artifact's ID across a change of natural identity.

        This is the seam §116 requires: Smith judges that a reworded
        requirement or a moved route is still the same artifact, and this
        service performs the deterministic half. The ID does not change.
        """
        with self._lock:
            artifact_id = self.bindings.get(old_key)
            if not artifact_id:
                raise InvalidArtifactId(f"nothing bound to {old_key!r}")
            occupant = self.bindings.get(new_key)
            if occupant and occupant != artifact_id:
                raise InvalidArtifactId(
                    f"{new_key!r} already belongs to {occupant}; "
                    "two artifacts cannot share one identity"
                )
            del self.bindings[old_key]
            self.bindings[new_key] = artifact_id
            return artifact_id

    def retire(self, artifact_id: str) -> None:
        """Mark an artifact gone. Its ID is never handed to anything else."""
        parse_id(artifact_id)  # validates
        with self._lock:
            self.retired.add(artifact_id)

    # -- lookups ------------------------------------------------------------

    def lookup(self, natural_key: str) -> str | None:
        return self.bindings.get(natural_key)

    def key_for(self, artifact_id: str) -> str | None:
        for key, value in self.bindings.items():
            if value == artifact_id:
                return key
        return None

    def is_retired(self, artifact_id: str) -> bool:
        return artifact_id in self.retired

    def allocated(self, prefix: str | None = None) -> list[str]:
        ids = sorted(self.bindings.values(), key=lambda i: parse_id(i))
        if prefix:
            ids = [i for i in ids if parse_id(i)[0] == prefix.upper()]
        return ids
