"""An observer repair is an edit of what the node wrote, not a second writing.

MEASURED. On a master-data build, five nodes the observer still judges —
testing, composition, page details, business rules, UX architecture — each
took 163-238 seconds, and in every one the repair re-authored the WHOLE
output. The application model is the clearest case: its first pass wrote
10,492 output tokens in 92 seconds, the observer flagged a few points, and
the repair wrote 10,240 tokens again in 80 seconds to change them. Output
tokens are both the slow part and the expensive part of a call, and a repair
paid for all of them twice.

Here the model is shown its current output and the findings and returns JSON
Patch edits (RFC 6902) against that output. The edited artifacts go through
exactly the same apply path as a rewrite would — the contract, the section
schemas, the capability boundary — so nothing gets weaker, only smaller. And
a patch that cannot be used for any reason falls back to the full rewrite
this replaces, so it can only save time, never cost a repair.

What is edited is precisely what the subject authored: the orchestrator
tracks those identities per subject, and a singleton section the node owns is
included whole. Keys come from the id registry, so an edited artifact keeps
its id even when the edit changes the text its key was derived from.

`page_layouts` has its own patcher (`page_patch`) for trees, and is not
judged by the observer any more; this is for everything else.
"""
from __future__ import annotations

import copy
import dataclasses
import json
import logging
import time
from typing import Any, Callable, Iterable

logger = logging.getLogger(__name__)

#: The largest edit that is still an edit. A repair that needs more than this
#: is closer to a rewrite, and the rewrite path handles that correctly.
MAX_EDITS = 60

#: Effort for the edit call. At the node's own effort (high) an edit spends
#: as long reasoning as a rewrite does writing: business_rules took 48s against
#: 26-43s rewrites. Replayed on dcfresh1's real findings, low and medium both
#: produced the one right edit in 4-14s; medium explained itself better. The
#: observer re-judges every repair, so a thin edit is caught, not shipped.
EDIT_EFFORT = "medium"

#: Fields the document sets itself. Never shown to the model as editable and
#: never sent back in a proposal.
_DOCUMENT_FIELDS = ("id", "status", "syncNote", "version", "createdAt",
                    "updatedAt", "changeHistory")

PATCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["edits", "note"],
    "properties": {
        "edits": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["op", "path", "value"],
                "properties": {
                    "op": {"type": "string", "enum": ["add", "replace", "remove"]},
                    "path": {"type": "string"},
                    # Structured outputs cannot carry a free-form value, so it
                    # travels as JSON text, like a proposal body does.
                    "value": {"type": "string"},
                },
            },
        },
        "note": {"type": "string"},
    },
}


#: How an edited repair announces itself in its result's assumptions.
EDIT_NOTE = "repaired in place with"


def was_edited(result: Any) -> bool:
    """Whether a repair's result came from an edit rather than a rewrite."""
    notes = getattr(result, "assumptions", None) or ()
    return bool(notes) and str(notes[0]).startswith(EDIT_NOTE)


class EditUnusable(ValueError):
    """The edit could not be applied as given; the caller rewrites instead."""


def _rows(doc: dict, section: str) -> list[dict]:
    node: Any = doc
    for part in section.split("."):
        node = node.get(part) if isinstance(node, dict) else None
    return [r for r in (node or []) if isinstance(r, dict)] if isinstance(node, list) else []


def _clean(value: Any) -> Any:
    """The body without the document's own bookkeeping, AT EVERY DEPTH.

    A product's capabilities each carry their own `status`. Shown to the model
    they read as editable, and a live repair did exactly that: asked for a
    missing capability, it marked an existing one DEPRECATED and wrote it a
    sync note. A rewrite never sees these fields either, so hiding them makes
    an edit exactly as informed as a rewrite and no more tempted.
    """
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items() if k not in _DOCUMENT_FIELDS}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def editable_artifacts(doc: dict, node_produces: Iterable[str],
                       identities: Iterable[tuple], *,
                       output_dir: Any = None) -> list[dict]:
    """What this subject authored, as ``[{section, natural_key, body}]``.

    ``identities`` are the orchestrator's record of the subject's accepted
    answer (see ``_proposed_identities``): ``("id", section, id)`` and
    ``("keyed", section, key)``. Singleton sections the node produces carry no
    identity and are included whole.
    """
    from services.blueprint.service import KEYED_LIST_SECTIONS, SINGLETON_SECTIONS

    alloc = None
    if output_dir:
        try:
            from services.blueprint.ids import IdAllocator
            alloc = IdAllocator.load(output_dir=output_dir)
        except Exception:  # noqa: BLE001 — keys then fall back to the id
            alloc = None

    out: list[dict] = []
    for ident in sorted(identities, key=lambda t: tuple(str(x) for x in t)):
        kind, section, ref = ident
        if kind == "id":
            row = next((r for r in _rows(doc, section) if r.get("id") == ref), None)
            if row is None or row.get("status") in ("DEPRECATED", "SUPERSEDED"):
                continue
            key = (alloc.key_for(ref) if alloc is not None else None) or str(ref)
            out.append({"section": section, "natural_key": key, "body": _clean(row)})
        elif kind == "keyed":
            fields = KEYED_LIST_SECTIONS.get(section) or ()
            row = next((r for r in _rows(doc, section)
                        if tuple(r.get(f) for f in fields) == tuple(ref)), None)
            if row is None:
                continue
            out.append({"section": section,
                        "natural_key": ":".join(str(x) for x in ref),
                        "body": _clean(row)})
    for section in node_produces:
        if section in SINGLETON_SECTIONS and isinstance(doc.get(section), dict) and doc[section]:
            out.append({"section": section, "natural_key": section,
                        "body": _clean(doc[section])})
    return out


def build_edit_prompt(system: str, artifacts: list[dict], feedback: str,
                      context: str = "", *, refused: bool = False) -> tuple[str, str]:
    """The node's own system prompt — its contract and section shapes — with an
    edit request in place of the authoring request.

    ``refused``: the artifacts were turned back by the Blueprint contract, not
    accepted and then judged. The instruction differs in one thing — WHO found
    the fault and what it is — and the edit is the same cheap move."""
    if refused:
        why = ("You wrote the artifacts below and the Blueprint contract REFUSED "
               "them, for the specific reasons listed. Nothing was kept. Fix "
               "exactly those faults by returning ")
    else:
        why = ("You wrote the artifacts below and they were accepted. An observer "
               "then found the specific problems listed. Fix exactly those "
               "problems by returning ")
    system = system + (
        "\n\n---\nTHIS CALL IS A REPAIR, NOT A NEW AUTHORING. " + why +
        "JSON Patch edits (RFC 6902) against the document "
        "`{\"artifacts\": [...]}` shown — and nothing else.\n\n"
        "Rules:\n"
        "- Paths are JSON Pointers into that document, e.g. "
        "`/artifacts/2/body/statement`, `/artifacts/0/body/tasks/-` (append), "
        "`/artifacts/-` (a new artifact, as {section, natural_key, body}).\n"
        "- `value` is the new value written as JSON text: `\"\\\"text\\\"\"` for "
        "a string, `\"[1, 2]\"` for a list, `\"{...}\"` for an object. Use "
        "`\"null\"` for a remove.\n"
        "- Edit the smallest thing that fixes each finding. Everything a "
        "finding does not name stays exactly as it is.\n"
        "- Never change an artifact's `section` or `natural_key`.\n"
        f"- At most {MAX_EDITS} edits. If a finding cannot be fixed by editing "
        "these artifacts, leave it and say so in `note`.\n"
        "- Return {\"edits\": [...], \"note\": \"...\"}."
    )
    # THE SAME CONTEXT THE AUTHOR HAD. Findings name requirements and other
    # sections ("REQ-004: ..."); without the Blueprint the model would be
    # editing blind. Input is the cheap, fast part of a call — the output is
    # what an edit saves, and it stays small either way.
    user = (
        (context.strip() + "\n\n---\n\n" if context else "")
        + ("REPAIR REQUEST. The contract's refusal:\n\n" if refused
           else "REPAIR REQUEST. The observer's findings:\n\n") + (feedback or "").strip()
        + "\n\nYour current output:\n\n```json\n"
        + json.dumps({"artifacts": artifacts}, indent=1, ensure_ascii=False)
        + "\n```"
    )
    return system, user


def apply_edits(artifacts: list[dict], edits: list[dict],
                allowed_sections: Iterable[str]) -> list[dict]:
    """The artifacts with the edits applied — a copy, validated for shape."""
    import jsonpatch

    if not edits:
        raise EditUnusable("no edits")
    if len(edits) > MAX_EDITS:
        raise EditUnusable(f"{len(edits)} edits — more than {MAX_EDITS}")
    ops = []
    for e in edits:
        path = str(e.get("path") or "")
        if not path.startswith("/artifacts"):
            raise EditUnusable(f"edit outside the artifacts: {path!r}")
        if path.endswith("/section") or path.endswith("/natural_key"):
            raise EditUnusable(f"an edit may not re-key an artifact: {path!r}")
        if path.rsplit("/", 1)[-1] in _DOCUMENT_FIELDS:
            # Status, sync notes and ids are the document's, set by apply and
            # by the observer's flag. An author editing them is not repairing.
            raise EditUnusable(f"an edit may not set a document field: {path!r}")
        op = {"op": e.get("op"), "path": path}
        if op["op"] != "remove":
            try:
                op["value"] = json.loads(e.get("value") if isinstance(e.get("value"), str)
                                         else json.dumps(e.get("value")))
            except (TypeError, ValueError) as exc:
                raise EditUnusable(f"value at {path} is not JSON: {exc}") from exc
        ops.append(op)
    try:
        patched = jsonpatch.apply_patch({"artifacts": copy.deepcopy(artifacts)},
                                        ops, in_place=False)["artifacts"]
    except Exception as exc:  # noqa: BLE001 — jsonpatch raises several types
        raise EditUnusable(f"patch does not apply: {exc}") from exc
    allowed = set(allowed_sections)
    for a in patched:
        if not isinstance(a, dict) or not isinstance(a.get("body"), dict):
            raise EditUnusable("an artifact lost its body")
        if a.get("section") not in allowed:
            raise EditUnusable(f"an artifact in {a.get('section')!r}, "
                               "which this node does not write")
        if not a.get("natural_key"):
            raise EditUnusable("an artifact has no key")
    return patched


def patch_node_output(spec: Any, client: Callable[..., Any], *, system: str,
                      produces: Iterable[str], task_id: str, context: str = "",
                      usage: Any = None, project: str = "", refused: bool = False) -> Any:
    """An AgentResult re-proposing the subject's artifacts with the edits
    applied — or ``None``, meaning: rewrite in full as before."""
    from services.blueprint.agent_contract import AgentResult, ArtifactProposal

    artifacts = list(getattr(spec, "current", ()) or ())
    if not artifacts or not getattr(spec, "feedback", ""):
        return None
    # THE FINDINGS, WITHOUT "AUTHOR IT AGAIN". The observer's brief is written
    # for a rewrite — "Your reply REPLACES what you wrote" — and handed to an
    # editor it contradicts the one instruction that makes this cheap.
    from services.blueprint.page_patch import findings_of
    edit_system, user = build_edit_prompt(
        system, artifacts,
        # A refusal is already a list of faults, one per attempt; the
        # observer's brief has framing to strip.
        spec.feedback if refused else findings_of(spec.feedback), context, refused=refused)
    if dataclasses.is_dataclass(client) and hasattr(client, "effort"):
        client = dataclasses.replace(client, effort=EDIT_EFFORT)
    t0 = time.monotonic()
    try:
        raw = client(system=edit_system, user=user, schema=PATCH_SCHEMA)
    except Exception as exc:  # noqa: BLE001 — a failed edit is a rewrite
        logger.info("[edit-repair] %s: model call failed (%s) — rewriting",
                    spec.node, str(exc)[:160])
        return None
    reply_usage = getattr(raw, "usage", None)
    if usage is not None and reply_usage is not None:
        try:
            usage.record(node=spec.node, agent=f"{spec.agent}:edit",
                         usage=reply_usage, elapsed_s=time.monotonic() - t0,
                         project=project)
        except Exception:  # noqa: BLE001
            pass
    try:
        data = json.loads(str(getattr(raw, "text", raw)))
        edits = [e for e in (data.get("edits") or []) if isinstance(e, dict)]
        patched = apply_edits(artifacts, edits, produces)
    except (EditUnusable, ValueError, AttributeError) as exc:
        logger.info("[edit-repair] %s: %s — rewriting", spec.node, str(exc)[:200])
        return None
    note = str(data.get("note") or "")
    logger.info("[edit-repair] %s%s: %d edit(s) instead of a rewrite%s",
                spec.node, f":{spec.subject}" if getattr(spec, "subject", "") else "",
                len(edits), f" — {note[:120]}" if note else "")
    return AgentResult(
        task_id=task_id, agent=spec.agent, confidence=0.9,
        proposals=[ArtifactProposal(section=a["section"],
                                    natural_key=str(a["natural_key"]),
                                    body=a["body"]) for a in patched],
        assumptions=[f"{EDIT_NOTE} {len(edits)} edit(s)"
                     + (f": {note[:200]}" if note else "")],
    )


__all__ = ["PATCH_SCHEMA", "MAX_EDITS", "EditUnusable", "editable_artifacts",
           "build_edit_prompt", "apply_edits", "patch_node_output", "EDIT_NOTE",
           "was_edited"]
