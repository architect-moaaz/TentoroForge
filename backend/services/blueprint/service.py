"""Blueprint Service (PRD §97) — custody of the Living Application Blueprint.

Per §115 the source of truth runs:

    Approved User Intent  →  Living Blueprint  →  Generated Implementation

and per §120 anything that mutates application behaviour without passing
through the Blueprint is architecturally incorrect. This module is the "passing
through" — the only supported way to change an application's definition.

What it owns (all deterministic; no LLM calls here, per §116)
------------------------------------------------------------
* **Validation** against the generated contract in
  ``contracts/blueprint.schema.json``, which is emitted from the Zod source in
  ``packages/schema/src/blueprint``. One definition, two languages.
* **Identity** — every artifact gets its ID from :class:`IdAllocator`, so a
  re-run cannot renumber (§12).
* **Versioning** (§91) — an accepted change produces a new version, and the
  prior version is snapshotted so §93 rollback has something to restore.
* **Change history** (§92) — every mutation records the request, the RFC-6902
  diff, and which artifacts it touched.
* **Status transitions** (§22) — including ``mark_out_of_sync``, which is what
  §76 requires *instead of* silently repairing generated output.

What it deliberately does not do
--------------------------------
It does not decide *what* should change — that is Smith's job. It does not
repair. When something is inconsistent it records the inconsistency and lets
verification surface it; a service that quietly fixed things would recreate the
post-generation repair chain this architecture exists to replace.

Storage
-------
``<output_dir>/.forge/blueprint/current.json`` plus one snapshot per version
under ``versions/``. Note this is *not* ``.forge/blueprint.json`` — that path
belongs to the legacy :mod:`services.smith_blueprint` and the two must not
fight while both exist. Export (§83) copies ``current.json`` to the package
root as ``blueprint.json``.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import jsonpatch
from jsonschema import Draft7Validator

from services.blueprint.ids import IdAllocator, is_valid_id, parse_id

CONTRACT_PATH = Path(__file__).resolve().parents[2] / "contracts" / "blueprint.schema.json"

#: §22. Terminal states still permit revival — a DEPRECATED artifact that comes
#: back reuses its own ID (see IdAllocator.allocate).
VALID_STATUSES = (
    "PROPOSED",
    "APPROVED",
    "PLANNED",
    "GENERATING",
    "IMPLEMENTED",
    "VERIFYING",
    "VERIFIED",
    "OUT_OF_SYNC",
    "FAILED",
    "DEPRECATED",
)

#: Sections that are a single object rather than a list of ID-bearing
#: artifacts. They carry no ``id`` and no ``status``, so they are written by
#: merge rather than by allocate-and-append.
SINGLETON_SECTIONS: frozenset[str] = frozenset({
    "product", "navigation", "designSystem", "uiRegistry", "security",
    "runtime", "database", "deployment", "completeness",
})

#: Lists whose members carry no id of their own, identified instead by a
#: composite of real fields. A relationship *is* its (from, to, kind) — giving
#: it a synthetic id would let the same edge be declared twice.
KEYED_LIST_SECTIONS: dict[str, tuple[str, ...]] = {
    "codeMap": ("artifact",),
    # One template per pattern — re-authoring `entity_list` replaces it rather
    # than accumulating a second structure for the same pattern.
    "patternTemplates": ("pattern",),
    # One tree per page — re-authoring a page replaces its layout rather than
    # accumulating a second one for the same page.
    "pageLayouts": ("page",),
    "data.relationships": ("from", "to", "kind"),
    "data.constraints": ("entity", "kind", "expression"),
}

#: Blueprint sections holding a list of ID-bearing artifacts, and the prefix
#: each uses. Drives generic lookup/status operations.
ARTIFACT_SECTIONS: dict[str, str] = {
    "roles": "ROLE",
    "permissions": "PERM",
    "modules": "MODULE",
    "pages": "PAGE",
    "components": "CMP",
    "widgets": "WIDGET",
    "workflows": "FLOW",
    "businessRules": "RULE",
    "apis": "API",
    "integrations": "INT",
    "requirements": "REQ",
    "tests": "TEST",
    "decisions": "DEC",
}


class BlueprintInvalid(ValueError):
    """The Blueprint does not satisfy the generated JSON Schema contract."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__(
            f"blueprint failed contract validation ({len(errors)} error(s)):\n  "
            + "\n  ".join(errors[:10])
        )


class ArtifactNotFound(KeyError):
    pass


class IdentityCollision(ValueError):
    """An ID is claimed by two different artifacts.

    Raised when :class:`IdAllocator` and the Blueprint document disagree about
    who owns an ID. The usual cause is a document loaded into an ``output_dir``
    whose ``.forge/ids.json`` never saw it: the counters start at zero and mint
    an ID the document is already using.

    §120 puts the Blueprint in charge and §76 forbids quiet repair, so this is
    a refusal rather than a merge — fusing the two artifacts would destroy one
    of them with no record that it ever existed.
    """


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_validator() -> Draft7Validator:
    if not CONTRACT_PATH.exists():
        raise FileNotFoundError(
            f"{CONTRACT_PATH} is missing. Generate it with:\n"
            "  npm run emit:blueprint-schema --workspace=packages/schema"
        )
    return Draft7Validator(json.loads(CONTRACT_PATH.read_text("utf-8")))


def empty_blueprint(*, app_id: str, name: str, domain: str, description: str = "") -> dict:
    """The minimum valid Blueprint. Every other section defaults."""
    return {
        "schemaVersion": "1",
        "version": 1,
        "state": "DISCOVERY",
        "application": {
            "id": app_id,
            "name": name,
            "domain": domain,
            "description": description,
        },
    }


def reference_fields() -> dict[str, set[str]]:
    """Which properties hold an artifact ID, derived from the contract.

    Found by their §12 pattern rather than hardcoded, so adding a reference to
    the schema makes it resolvable here automatically. Restricting rewriting to
    these fields is what stops a description that happens to mention
    "Candidate" being mangled into an ID.

    ``zodToJsonSchema`` folds identical subschemas into ``$ref`` pointers — the
    first ``EntityId`` becomes canonical and every other one refs it — so the
    pattern is usually one dereference away and a naive walk finds almost none.
    """
    contract = json.loads(CONTRACT_PATH.read_text("utf-8"))
    id_pattern = re.compile(r"\^[A-Z]+-")

    def deref(node: Any, depth: int = 0) -> Any:
        """Follow a local ``#/a/b/c`` pointer; bounded against a ref cycle."""
        while isinstance(node, dict) and "$ref" in node and depth < 10:
            ref = node["$ref"]
            if not ref.startswith("#/"):
                return node
            target: Any = contract
            for part in ref[2:].split("/"):
                if not isinstance(target, dict) or part not in target:
                    return node
                target = target[part]
            node, depth = target, depth + 1
        return node

    def holds_id(prop: Any) -> bool:
        prop = deref(prop)
        if not isinstance(prop, dict):
            return False
        pat = prop.get("pattern")
        if isinstance(pat, str) and id_pattern.match(pat):
            return True
        item = deref(prop.get("items")) if "items" in prop else None
        if isinstance(item, dict):
            ipat = item.get("pattern")
            return isinstance(ipat, str) and bool(id_pattern.match(ipat))
        return False

    out: dict[str, set[str]] = {}

    def scan(node: Any, section: str, depth: int = 0) -> None:
        """Recurse: references nest. ``navigation.tree[].children[].page`` is a
        page reference four levels down, and a top-level-only scan misses every
        one of them — which is how a nav tree full of routes reached the
        validator."""
        node = deref(node)
        if not isinstance(node, dict) or depth > 8:
            return
        for key, prop in (node.get("properties") or {}).items():
            if holds_id(prop):
                out.setdefault(section, set()).add(key)
                continue
            prop = deref(prop)
            if not isinstance(prop, dict):
                continue
            scan(prop, section, depth + 1)
            scan(deref(prop.get("items")) or {}, section, depth + 1)

    for section, node in (contract.get("properties") or {}).items():
        node = deref(node)
        if section == "data":
            for child, cnode in (node.get("properties") or {}).items():
                cnode = deref(cnode)
                scan(cnode.get("items", cnode), f"data.{child}")
        else:
            scan(node.get("items", node), section)
    return out


def resolve_batch_references(
    proposals: list[tuple[str, str, dict]], allocated: dict[str, str]
) -> None:
    """Rewrite in-batch references from natural keys to allocated IDs.

    An agent proposing six entities and eight relationships in one turn cannot
    reference the entities by ID — they do not have one until this layer
    assigns it, and inventing one is forbidden (§12/§116). So it references
    them by natural key or by name, and this closes the loop before validation.

    Mutates the proposal bodies in place. Values that resolve to nothing are
    left alone, so an unresolvable reference fails contract validation loudly
    rather than being silently dropped.
    """
    refs = reference_fields()

    def resolve(value: Any) -> Any:
        if isinstance(value, str):
            return allocated.get(value, value)
        if isinstance(value, list):
            return [resolve(v) for v in value]
        return value

    def walk(node: Any, fields: set[str], depth: int = 0) -> None:
        """Rewrite reference-typed keys wherever they appear in the body.

        Keyed on field name within the section rather than on a schema path:
        paths through arrays and ``$ref`` folding are awkward to track, and the
        names are already scoped to the section, so a stray match is unlikely.
        ``id`` is never rewritten — an artifact's own identity is assigned, not
        referenced.
        """
        if depth > 12:
            return
        if isinstance(node, dict):
            for key, value in node.items():
                if key in fields and key != "id":
                    node[key] = resolve(value)
                else:
                    walk(value, fields, depth + 1)
        elif isinstance(node, list):
            for item in node:
                walk(item, fields, depth + 1)

    for section, _key, body in proposals:
        fields = refs.get(section, set())
        if fields:
            walk(body, fields)


@dataclass
class BlueprintService:
    """Load → mutate → validate → version → save, for one application."""

    output_dir: str
    doc: dict = field(default_factory=dict)
    _validator: Draft7Validator | None = field(default=None, repr=False, compare=False)

    # -- paths --------------------------------------------------------------

    @property
    def root(self) -> Path:
        return Path(self.output_dir) / ".forge" / "blueprint"

    @property
    def current_path(self) -> Path:
        return self.root / "current.json"

    def version_path(self, version: int) -> Path:
        return self.root / "versions" / f"v{version}.json"

    # -- lifecycle ----------------------------------------------------------

    @classmethod
    def create(
        cls, *, output_dir: str | Path, app_id: str, name: str, domain: str,
        description: str = "",
    ) -> "BlueprintService":
        svc = cls(output_dir=str(output_dir))
        svc.doc = empty_blueprint(
            app_id=app_id, name=name, domain=domain, description=description
        )
        svc.validate()
        svc.save()
        return svc

    @classmethod
    def load(cls, *, output_dir: str | Path) -> "BlueprintService":
        svc = cls(output_dir=str(output_dir))
        p = svc.current_path
        if not p.exists():
            raise FileNotFoundError(f"no blueprint at {p}")
        try:
            svc.doc = json.loads(p.read_text("utf-8"))
        except json.JSONDecodeError as exc:
            # Never fall back to an empty Blueprint: that would silently
            # discard the application's definition and renumber everything.
            raise BlueprintInvalid([f"{p} is not valid JSON: {exc}"]) from exc
        return svc

    def save(self) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.current_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.doc, indent=2, sort_keys=True), "utf-8")
        os.replace(tmp, self.current_path)
        return self.current_path

    # -- validation (§76) ---------------------------------------------------

    def validate(self) -> None:
        """Raise :class:`BlueprintInvalid` if the document breaks the contract."""
        if self._validator is None:
            self._validator = _load_validator()
        errors = sorted(self._validator.iter_errors(self.doc), key=lambda e: list(e.path))
        if errors:
            raise BlueprintInvalid(
                [f"{'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}"
                 for e in errors]
            )

    def is_valid(self) -> bool:
        try:
            self.validate()
            return True
        except BlueprintInvalid:
            return False

    # -- artifact access ----------------------------------------------------

    def artifacts(self, section: str) -> list[dict]:
        if section not in ARTIFACT_SECTIONS:
            raise KeyError(f"{section!r} is not an artifact section")
        return self.doc.setdefault(section, [])

    def find(self, artifact_id: str) -> tuple[str, dict]:
        """Return ``(section, artifact)``. Entities live under ``data``."""
        if not is_valid_id(artifact_id):
            raise ArtifactNotFound(f"malformed id: {artifact_id!r}")
        prefix, _ = parse_id(artifact_id)
        if prefix == "ENTITY":
            for ent in self.doc.get("data", {}).get("entities", []):
                if ent.get("id") == artifact_id:
                    return "data.entities", ent
            raise ArtifactNotFound(artifact_id)
        for section, sec_prefix in ARTIFACT_SECTIONS.items():
            if sec_prefix != prefix:
                continue
            for art in self.doc.get(section, []) or []:
                if art.get("id") == artifact_id:
                    return section, art
        raise ArtifactNotFound(artifact_id)

    def upsert(self, section: str, artifact: dict, *, natural_key: str) -> dict:
        """Insert or update one artifact, allocating its ID if it has none.

        The ID comes from :class:`IdAllocator` keyed on ``natural_key``, so
        calling this twice for the same artifact updates it rather than
        creating a duplicate — which is what makes re-generation idempotent.

        Three kinds of section, three write paths. Singleton sections
        (``database``, ``security``, …) are objects with no id and no status,
        so they merge; ``codeMap`` is a list keyed by ``artifact``; everything
        else is an ID-bearing artifact list.

        Raises :class:`IdentityCollision` when the allocator hands out an ID
        the document has already given to a different artifact — see that
        class for why that is a refusal and not a merge.
        """
        if section in SINGLETON_SECTIONS:
            current = self.doc.get(section)
            merged = {**current, **artifact} if isinstance(current, dict) else dict(artifact)
            self.doc[section] = merged
            return merged

        if section in KEYED_LIST_SECTIONS:
            keys = KEYED_LIST_SECTIONS[section]
            if "." in section:
                parent, child = section.split(".", 1)
                bucket = self.doc.setdefault(parent, {}).setdefault(child, [])
            else:
                bucket = self.doc.setdefault(section, [])

            def identity(d: dict) -> tuple:
                return tuple(d.get(k) for k in keys)

            for i, existing in enumerate(bucket):
                if identity(existing) == identity(artifact):
                    bucket[i] = {**existing, **artifact}
                    return bucket[i]
            bucket.append(dict(artifact))
            return bucket[-1]

        if section == "data.entities":
            prefix = "ENTITY"
            bucket = self.doc.setdefault("data", {}).setdefault("entities", [])
        else:
            prefix = ARTIFACT_SECTIONS[section]
            bucket = self.artifacts(section)

        # Raising inside the session skips its ``save()``, so a refusal leaves
        # the registry exactly as it was.
        with IdAllocator.session(output_dir=self.output_dir) as alloc:
            claimed = artifact.get("id")
            # Read before writing: after allocate/bind the registry can no
            # longer say who held the id a moment ago.
            already_bound = alloc.lookup(natural_key)
            if claimed:
                owner = alloc.key_for(claimed)
                if owner is not None and owner != natural_key:
                    raise IdentityCollision(
                        f"{section}: {claimed} belongs to {owner!r}, so "
                        f"{natural_key!r} cannot claim it; two artifacts "
                        "cannot share one identity. If this artifact's natural "
                        "identity changed, carry the id across with "
                        "IdAllocator.rebind()."
                    )
                alloc.bind(natural_key, claimed)
                artifact_id = claimed
            else:
                artifact_id = alloc.allocate(prefix, natural_key)
                # The allocator is monotonic and never re-issues, so an id it
                # has just minted cannot legitimately be in the document
                # already. When it is, the registry has fallen out of step with
                # the document and is minting over the top of it.
                if already_bound is None and any(
                    a.get("id") == artifact_id for a in bucket
                ):
                    raise IdentityCollision(
                        f"{section}: allocated {artifact_id} for new artifact "
                        f"{natural_key!r}, but the Blueprint already has an "
                        f"artifact with that id. The registry at "
                        f"{IdAllocator.path_for(self.output_dir)} is out of "
                        "step with the document — bind the ids the document "
                        "already uses into it (IdAllocator.bind, or "
                        "services.smith.smith.bootstrap) before upserting."
                    )

        merged = {**artifact, "id": artifact_id}
        merged.setdefault("status", "PROPOSED")
        for i, existing in enumerate(bucket):
            if existing.get("id") == artifact_id:
                bucket[i] = {**existing, **merged}
                return bucket[i]
        bucket.append(merged)
        return merged

    # -- status (§22, §76) --------------------------------------------------

    def set_status(self, artifact_id: str, status: str, *, note: str | None = None) -> dict:
        if status not in VALID_STATUSES:
            raise ValueError(f"{status!r} is not a §22 artifact status")
        _, art = self.find(artifact_id)
        art["status"] = status
        if note is not None:
            art["syncNote"] = note
        elif status not in ("OUT_OF_SYNC", "FAILED"):
            art.pop("syncNote", None)
        return art

    def mark_out_of_sync(self, artifact_id: str, note: str) -> dict:
        """§76 — record that Blueprint and implementation disagree.

        This is the whole point of the architecture: divergence becomes a
        visible state on a named artifact instead of an invisible repair.
        """
        return self.set_status(artifact_id, "OUT_OF_SYNC", note=note)

    def out_of_sync(self) -> list[dict]:
        found: list[dict] = []
        for section in list(ARTIFACT_SECTIONS) + ["__entities__"]:
            items = (
                self.doc.get("data", {}).get("entities", [])
                if section == "__entities__"
                else self.doc.get(section, []) or []
            )
            found.extend(a for a in items if a.get("status") == "OUT_OF_SYNC")
        return found

    # -- change + versioning (§91, §92) -------------------------------------

    def commit(
        self,
        *,
        user_request: str,
        smith_interpretation: str = "",
        before: dict | None = None,
        affected: Iterable[str] = (),
        migrations: Iterable[str] = (),
        tests: Iterable[str] = (),
        verification: str = "skipped",
    ) -> dict:
        """Validate, snapshot the prior version, bump, and record history.

        ``before`` is the document as it was when this change began; pass
        :meth:`snapshot` taken before mutating. The RFC-6902 diff between the
        two becomes ``changeHistory[].blueprintDiff`` (§92).
        """
        self.validate()  # never version an invalid Blueprint

        prior = before if before is not None else {}
        prior_version = int(prior.get("version") or self.doc.get("version") or 1)

        # snapshot the *previous* state so §93 rollback has a target
        if before is not None:
            self.root.joinpath("versions").mkdir(parents=True, exist_ok=True)
            self.version_path(prior_version).write_text(
                json.dumps(before, indent=2, sort_keys=True), "utf-8"
            )

        diff = jsonpatch.make_patch(prior or {}, self.doc).patch if before is not None else []
        new_version = prior_version + 1 if before is not None else prior_version

        record = {
            "version": new_version,
            "at": _now(),
            "userRequest": user_request,
            "smithInterpretation": smith_interpretation,
            "blueprintDiff": diff,
            "affectedArtifacts": list(affected),
            "migrations": list(migrations),
            "tests": list(tests),
            "verification": verification,
        }
        self.doc["version"] = new_version
        self.doc.setdefault("changeHistory", []).append(record)
        self.validate()
        self.save()
        return record

    def snapshot(self) -> dict:
        """Deep copy of the current document, for passing to :meth:`commit`."""
        return json.loads(json.dumps(self.doc))

    def versions(self) -> list[int]:
        d = self.root / "versions"
        if not d.exists():
            return []
        out = []
        for p in d.glob("v*.json"):
            try:
                out.append(int(p.stem[1:]))
            except ValueError:
                continue
        return sorted(out)

    def rollback(self, version: int) -> dict:
        """§93 — restore a previously saved version.

        A failed modification must never destroy the last working application,
        so the current document is snapshotted before being replaced.
        """
        target = self.version_path(version)
        if not target.exists():
            raise FileNotFoundError(f"no snapshot for version {version}")
        current_version = int(self.doc.get("version") or 1)
        self.root.joinpath("versions").mkdir(parents=True, exist_ok=True)
        self.version_path(current_version).write_text(
            json.dumps(self.doc, indent=2, sort_keys=True), "utf-8"
        )
        self.doc = json.loads(target.read_text("utf-8"))
        self.validate()
        self.save()
        return self.doc

    # -- export (§83) -------------------------------------------------------

    def export_to(self, package_root: str | Path) -> Path:
        """Copy ``current.json`` to ``<package>/blueprint.json`` for §83.

        The exported package carries machine-readable application context so a
        project can later be re-imported (§4.6).
        """
        dest = Path(package_root) / "blueprint.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.current_path, dest)
        return dest
