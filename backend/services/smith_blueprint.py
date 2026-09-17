"""Smith Blueprint — per-project persistent memory.

The Blueprint is the single JSON document that captures *why* every
entity, page, workflow, and design decision exists in a generated
app. It's what makes Smith the app's architect rather than a
stateless chat bot: because the Blueprint travels with the code (in
``<output_dir>/.forge/blueprint.json``), Smith always loads a full
picture of what he built and why he built it that way.

See ``docs/superpowers/specs/2026-07-17-smith-as-architect.md``
sections 4-6 for the design intent this module implements. This
slice (S1) covers the file-persistence half of §6.1 only; the DB
index row is a follow-up.

Public surface:

  * :class:`Blueprint` — the in-memory dataclass with additive
    mutators (``set_domain``, ``add_entity``, ``add_page``,
    ``add_workflow``, ``add_design_decision``, ``append_change_log``)
    and ``load`` / ``save`` / ``fingerprint`` operations.
  * :class:`BlueprintPath` — resolves the on-disk location, kept
    separate so tests can point at a temp directory without touching
    the process cwd.

Design notes:

  * Writes are atomic (temp file + ``os.replace``). A crashed write
    can never leave a torn blueprint next to healthy code.
  * Unknown top-level fields survive round-trips — future slices can
    add sections without a data migration for older projects.
  * The ``fingerprint`` is a stable content hash for the staleness
    check in §6.6; two blueprints with the same fields in the same
    order produce the same fingerprint.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Path resolver
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class BlueprintPath:
    """Where the blueprint file lives on disk for a given output dir.

    Isolated in its own type so callers that only need to *reference*
    the path (staleness checks, git hooks) don't have to load the
    full blueprint."""
    output_dir: str

    @property
    def dir(self) -> Path:
        return Path(self.output_dir) / ".forge"

    @property
    def file(self) -> Path:
        return self.dir / "blueprint.json"


# --------------------------------------------------------------------------- #
# Blueprint dataclass
# --------------------------------------------------------------------------- #

_KNOWN_TOP_LEVEL_FIELDS = frozenset({
    "project_id", "domain", "entities", "workflows", "pages",
    "requirements", "business_rules", "design_decisions", "change_log",
})


@dataclass
class Blueprint:
    """The in-memory shape. See §6.2 of the spec for field semantics."""

    project_id: str
    domain: dict[str, Any] | None = None
    entities: list[dict[str, Any]] = field(default_factory=list)
    workflows: list[dict[str, Any]] = field(default_factory=list)
    pages: list[dict[str, Any]] = field(default_factory=list)
    # What the app must do, each line with where it came from (§14). Read
    # from the engine's document; Smith answers "which of these came from
    # the file I uploaded?" from the evidence, and from nowhere else.
    requirements: list[dict[str, Any]] = field(default_factory=list)
    #: The rules in force. Read for the same reason as the fields: a question
    #: Smith can answer from the document must not be asked of the person.
    business_rules: list[dict[str, Any]] = field(default_factory=list)
    #: The outside services, and for each one whether it is CONNECTED or only
    #: DECLARED. Not persisted here and not Smith's to save: the declaration
    #: belongs to the engine's document and the "is its key set" half belongs
    #: to the platform's credential store, so both are read at load. Without
    #: it "the confirmation email never came" was unanswerable — the context
    #: had no line about email at all, and Smith could only sympathise.
    integrations: list[dict[str, Any]] = field(default_factory=list)
    design_decisions: list[dict[str, Any]] = field(default_factory=list)
    change_log: list[dict[str, Any]] = field(default_factory=list)

    # Forward-compat bag: anything the loader doesn't recognize lives
    # here and round-trips on save so future readers still see it.
    _extras: dict[str, Any] = field(default_factory=dict)

    # Not persisted — the output_dir the load came from, so save()
    # knows where to write without the caller having to hand it back.
    _output_dir: str | None = field(default=None, repr=False, compare=False)

    # ---- persistence -----------------------------------------------------

    @classmethod
    def load(cls, *, project_id: str, output_dir: str) -> "Blueprint":
        """Load ``<output_dir>/.forge/blueprint.json``, or return an
        empty blueprint for that project if no file exists.

        The loader is tolerant: malformed JSON logs a warning and
        returns an empty blueprint (the caller can decide whether to
        overwrite or bail); unknown top-level fields are preserved."""
        # THE ENGINE'S DOCUMENT IS THE APPLICATION. Two stores exist: the DAG
        # writes .forge/blueprint/current.json and this class reads
        # .forge/blueprint.json. This used to prefer its own file and fall
        # back to the engine's, which is the wrong way round — the engine's
        # document changes on every build and every seam, and Smith's copy
        # changes when Smith happens to save. On a project with both, Smith
        # was reading an application as it stood some builds ago: a nurse
        # record with `yearsOfExperience` and no phone number, months after
        # the field was renamed and the phone number added. Asked to validate
        # the telephone number it asked whether one existed, correctly, from
        # a picture that was out of date.
        #
        # Read, not copied. Smith's own file still supplies what the engine's
        # has no notion of — the change log of Smith's moves — so nothing is
        # lost by preferring the truth for everything else.
        from services.smith.engine_blueprint_adapter import (
            load_engine_doc, to_smith_fields,
        )

        path = BlueprintPath(output_dir).file
        engine = load_engine_doc(output_dir)
        if engine:
            bp = cls(project_id=project_id)
            for key, value in to_smith_fields(engine).items():
                setattr(bp, key, value)
            # The connection state, which no document holds: a declaration is
            # in the engine's Blueprint and whether its credential is set is
            # in the platform's store. Read here, where the output_dir is
            # known, and only when something actually claims to serve a
            # runtime action — an application with no connections asks the
            # store nothing.
            from services.smith.engine_blueprint_adapter import connection_lines

            bp.integrations = connection_lines(engine, output_dir)
            if path.exists():
                try:
                    mine = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    mine = {}
                if isinstance(mine, dict):
                    bp.change_log = list(mine.get("change_log") or [])
                    bp._extras = {k: v for k, v in mine.items()
                                  if k not in _KNOWN_TOP_LEVEL_FIELDS and not k.startswith("_")}
            bp._output_dir = output_dir
            return bp

        if not path.exists():
            bp = cls(project_id=project_id)
            bp._output_dir = output_dir
            return bp

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning(
                "smith_blueprint: %s unreadable (%r); returning empty",
                path, exc,
            )
            bp = cls(project_id=project_id)
            bp._output_dir = output_dir
            return bp

        if not isinstance(raw, dict):
            logger.warning(
                "smith_blueprint: %s is not a JSON object; returning empty",
                path,
            )
            bp = cls(project_id=project_id)
            bp._output_dir = output_dir
            return bp

        extras = {k: v for k, v in raw.items()
                  if k not in _KNOWN_TOP_LEVEL_FIELDS and not k.startswith("_")}
        bp = cls(
            project_id=str(raw.get("project_id") or project_id),
            domain=raw.get("domain") if isinstance(raw.get("domain"), dict) else None,
            entities=list(raw.get("entities") or []),
            workflows=list(raw.get("workflows") or []),
            pages=list(raw.get("pages") or []),
            requirements=list(raw.get("requirements") or []),
            business_rules=list(raw.get("business_rules") or []),
            design_decisions=list(raw.get("design_decisions") or []),
            change_log=list(raw.get("change_log") or []),
            _extras=extras,
        )
        bp._output_dir = output_dir
        return bp

    def save(self) -> Path:
        """Write atomically to ``<output_dir>/.forge/blueprint.json``.

        Returns the final file path. Raises if ``load`` was never
        called with an ``output_dir`` (nowhere to write to)."""
        if not self._output_dir:
            raise ValueError(
                "Blueprint.save() requires the object to have been loaded "
                "with an output_dir (or set it explicitly)."
            )
        path = BlueprintPath(self._output_dir)
        path.dir.mkdir(parents=True, exist_ok=True)
        payload = self.to_dict()
        serialized = json.dumps(payload, indent=2, sort_keys=False,
                                ensure_ascii=False) + "\n"

        # temp file in the same directory so os.replace is atomic on
        # the same filesystem.
        fd, tmp_path = tempfile.mkstemp(
            prefix=".blueprint-", suffix=".tmp", dir=str(path.dir),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as tmp:
                tmp.write(serialized)
                tmp.flush()
                os.fsync(tmp.fileno())
            os.replace(tmp_path, path.file)
        except Exception:
            # Clean up the temp file if replace never ran.
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass
            raise
        return path.file

    def to_dict(self) -> dict[str, Any]:
        """The exact shape written to disk. Extras go LAST so the
        known keys stay in their canonical order at the top of the file
        for hand-reading."""
        base: dict[str, Any] = {
            "project_id": self.project_id,
            "domain": self.domain,
            "entities": list(self.entities),
            "workflows": list(self.workflows),
            "pages": list(self.pages),
            "requirements": list(self.requirements),
            "business_rules": list(self.business_rules),
            "design_decisions": list(self.design_decisions),
            "change_log": list(self.change_log),
        }
        for k, v in self._extras.items():
            base[k] = v
        return base

    def fingerprint(self) -> str:
        """Content hash of the blueprint. Two blueprints with the same
        fields in the same order produce the same fingerprint.

        Used by §6.6 to detect editor / external mutations between
        Smith turns — Smith caches the fingerprint at turn start and
        re-checks before writing."""
        canonical = json.dumps(self.to_dict(), sort_keys=True,
                               separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    # ---- mutators --------------------------------------------------------

    def set_domain(
        self, *,
        name: str,
        primary_actors: list[str],
        core_verbs: list[str],
        distinctive_shape: str,
        why: str,
    ) -> None:
        """Set the domain block. Called once during discovery; later
        Smith moves that redefine the domain overwrite this and log
        the amendment via ``append_change_log``."""
        self.domain = {
            "name": name,
            "primary_actors": list(primary_actors),
            "core_verbs": list(core_verbs),
            "distinctive_shape": distinctive_shape,
            "why": why,
        }

    def add_entity(
        self, *,
        name: str,
        table: str,
        purpose: str,
        key_fields: list[str],
        why_shaped_this_way: str,
    ) -> None:
        self.entities.append({
            "name": name,
            "table": table,
            "purpose": purpose,
            "key_fields": list(key_fields),
            "why_shaped_this_way": why_shaped_this_way,
        })

    def add_workflow(
        self, *,
        name: str,
        purpose: str,
        trigger: str,
        why: str,
    ) -> None:
        self.workflows.append({
            "name": name,
            "purpose": purpose,
            "trigger": trigger,
            "why": why,
        })

    def add_page(
        self, *,
        route: str,
        schema_path: str,
        role: str,
        notable_choices: list[dict[str, Any]] | None = None,
    ) -> None:
        self.pages.append({
            "route": route,
            "schema_path": schema_path,
            "role": role,
            "notable_choices": list(notable_choices or []),
        })

    def add_design_decision(
        self, *,
        topic: str,
        choice: str,
        why: str,
        authored_at: str,
    ) -> None:
        self.design_decisions.append({
            "topic": topic,
            "choice": choice,
            "why": why,
            "authored_at": authored_at,
        })

    def append_change_log(
        self, *,
        at: str,
        user_ask: str,
        smith_move: str,
        diff_summary: str,
        verified_by: list[str],
        why: str,
        source: str = "smith",
    ) -> None:
        """Add one entry to the change log.

        ``source`` distinguishes Smith's own moves (default), editor
        saves (``"editor"``), self-heal fixes (``"self-heal"``), and
        reconciled external edits (``"external"``). See §6.5-6.6 of
        the spec."""
        self.change_log.append({
            "at": at,
            "user_ask": user_ask,
            "smith_move": smith_move,
            "diff_summary": diff_summary,
            "verified_by": list(verified_by),
            "why": why,
            "source": source,
        })
