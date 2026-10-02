"""What every Blueprint-first change shares: re-run the node that owns a
section, briefed on what to change and what to keep; hold the reply to the
contract; commit it through the Blueprint; say what was refused.

`restyle` (designSystem), `workflow_change` (workflows) and
`navigation_change` (navigation) each did this in their own words. The
seams for access, rules and entities do it through here, so the fourth
copy is the last.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Callable

from services.llm_client import tell

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 2


class SectionChangeError(Exception):
    """The change could not be made, with the reason a user can act on."""


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:60] or "change"


def bind_ids(svc: Any) -> None:
    from services.smith.smith import bootstrap
    bootstrap(svc)


def record_requirement(svc: Any, text: str, owner: str) -> dict:
    """The ask as a requirement the owning section satisfies — what its agent
    authors from and what the observer grades against."""
    bind_ids(svc)
    body = {"description": text, "evidence": [{"message": text, "type": "conversation"}],
            "confidence": 1.0, "status": "APPROVED", "owner": owner}
    written = svc.upsert("requirements", body, natural_key=f"REQ:{slug(text)}")
    svc.save()
    return written


def executor_for(svc: Any, executor: Any, reasoning: Any) -> Any:
    if executor is not None:
        return executor
    from services.blueprint.executors import RunUsage, make_executor, tiered_router
    return make_executor(svc, tiered_router(reasoning=reasoning),
                         usage=RunUsage.for_app(svc, phase="change"), reasoning=reasoning)


def apply(svc: Any, request: str, proposals: list, *, interpretation: str, agent: str,
          app_root: str | None) -> tuple[Any, str]:
    """`apply_change` without the whole-DAG regeneration; (result, refusal)."""
    from services.blueprint.agent_contract import InvalidPatternTemplate, InvalidWorkflowStep, AuthorRefusal
    from services.blueprint.service import BlueprintInvalid
    from services.smith.change import apply_change
    bind_ids(svc)
    _as_patches(svc, proposals)
    try:
        out = apply_change(svc, request, proposals=list(proposals), interpretation=interpretation,
                           agent=agent, app_root=app_root, regenerate=False)
    except (BlueprintInvalid, AuthorRefusal) as exc:
        return None, f"{type(exc).__name__}: {exc}".replace("\n", " ")[:500]
    if not getattr(out, "applied", False):
        return None, str(getattr(out, "reason", "") or "refused")
    return out, ""


def _onto(have: dict, given: dict) -> dict:
    """`given` laid onto `have`, setting by setting: a nested setting merged
    the same way, and an empty value never wiping one that is there — the
    agent restated `photoEmbedding` with `embedding: {of: ""}` and the
    contract refused the whole change (2026-10-02)."""
    out = dict(have)
    for k, v in given.items():
        if v in (None, "", [], {}) and out.get(k) not in (None, "", [], {}):
            continue
        out[k] = _onto(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def _as_patches(svc: Any, proposals: list) -> None:
    """A change to a record type that exists is a patch onto it: a field the
    proposal leaves out is kept, and so is any setting of a field it does not
    restate. The data agent returns the whole record type, and what it left
    out was applied as a removal — asked for two-decimal prices it dropped
    `photoEmbedding` and the id's uniqueness; asked for unique names it
    dropped `isAvailable` (2026-10-02). Removing a field is `remove_field`;
    renaming one is `rename_field`, which moves its data."""
    entities = [e for e in (svc.doc.get("data") or {}).get("entities") or [] if isinstance(e, dict)]
    by_key = {str(e.get("id")): e for e in entities}
    by_key.update({str(e.get("name") or "").strip().lower(): e for e in entities})
    for prop in proposals:
        body = getattr(prop, "body", None)
        if getattr(prop, "section", "") != "data.entities" or not isinstance(body, dict) \
                or not isinstance(body.get("fields"), list):
            continue
        cur = by_key.get(str(body.get("id") or "")) or by_key.get(str(body.get("name") or "").strip().lower()) \
            or by_key.get(str(getattr(prop, "natural_key", "") or "").strip().lower())
        if cur is None:
            continue                       # a new record type is proposed whole
        given = {str(f.get("name")): f for f in body["fields"] if isinstance(f, dict) and f.get("name")}
        merged = [_onto(f, given[str(f.get("name"))]) if str(f.get("name")) in given else f
                  for f in cur.get("fields") or [] if isinstance(f, dict)]
        have = {str(f.get("name")) for f in merged}
        merged += [f for name, f in given.items() if name not in have]
        body["fields"] = merged


def pinned(svc: Any, proposals: list, section: str, artifact_id: str) -> list:
    """Proposals for `section` re-keyed to what the registry bound
    `artifact_id` to — so a reply keyed by whatever name the agent wrote
    updates the artifact instead of allocating a second one beside it."""
    from services.blueprint.agent_contract import ArtifactProposal
    from services.blueprint.ids import IdAllocator
    # BIND FIRST. `bootstrap` re-keys a section that has no natural-key scheme
    # (rules) under a content hash and drops the key it was upserted with, so
    # a key read before binding is one the apply will no longer find — and
    # the reply lands on a second id.
    bind_ids(svc)
    try:
        key = IdAllocator.load(output_dir=svc.output_dir).key_for(artifact_id)
    except Exception:  # noqa: BLE001
        key = None
    if not key:
        return list(proposals)
    return [ArtifactProposal(p.section, key, p.body) if p.section == section else p for p in proposals]


def rerun(svc: Any, node: str, *, brief: str, request: str, interpretation: str,
          subject: str = "", keep: Callable[[list], list] | None = None,
          executor: Any = None, reasoning: Any = None, app_root: str | None = None,
          empty: str = "the agent returned nothing usable", say: str = "") -> tuple[list, Any]:
    """Run the node that owns a section once (twice when refused), keep the
    proposals `keep` selects, commit them. Returns (proposals applied, result).
    """
    from services.blueprint.orchestrator import DAG, TaskSpec
    from services.smith.asked import with_their_words
    run = executor_for(svc, executor, reasoning)
    agent = DAG[node].agent
    # WHAT WAS ASKED, NOT ONLY SMITH'S READING OF IT — and, for the agents
    # whose slice holds no pages, which screens read the records they change.
    brief = with_their_words(brief)
    if node in ("entity_fields", "data_model", "business_rules"):
        from services.blueprint.page_usage import usage_brief
        used = usage_brief(svc.doc)
        if used:
            brief = f"{brief}\n\n{used}"
    feedback = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        spec = TaskSpec(task_id=f"smith-{node}-{slug(subject or request)[:24]}-{attempt}", node=node,
                        agent=agent, attempt=attempt, subject=subject, feedback=feedback, brief=brief)
        tell(reasoning, say or f"Re-deciding {node.replace('_', ' ')}: {request}.", "step")
        result = run(spec)
        props = list(getattr(result, "proposals", None) or [])
        props = keep(props) if keep else props
        if not props:
            feedback = empty
        else:
            out, refusal = apply(svc, request, props, interpretation=interpretation, agent=agent, app_root=app_root)
            if not refusal:
                return props, out
            feedback = refusal
        if attempt == MAX_ATTEMPTS:
            raise SectionChangeError(f"refused {MAX_ATTEMPTS} times and nothing has been changed. "
                                     f"The last reason was: {feedback}")
        tell(reasoning, f"That was refused — {feedback[:160]} Asking again.", "step")
    raise SectionChangeError("nothing was produced")   # unreachable


def find_named(rows: list, ref: str, *, id_prefix: str = "") -> dict | None:
    """The artifact a person means: its id, its exact name, or the one name
    that appears in what they said (or contains it)."""
    want = (ref or "").strip().lower()
    if not want:
        return None
    live = [r for r in rows if isinstance(r, dict) and r.get("status") != "DEPRECATED"]
    for r in live:
        if str(r.get("id") or "").lower() == want or str(r.get("name") or "").strip().lower() == want:
            return r
    hits = [r for r in live if str(r.get("name") or "").strip().lower()
            and (str(r.get("name")).strip().lower() in want or want in str(r.get("name")).strip().lower())]
    return hits[0] if len(hits) == 1 else None


def names(rows: list) -> str:
    return ", ".join(f"{r.get('name')} ({r.get('id')})" for r in rows
                     if isinstance(r, dict) and r.get("status") != "DEPRECATED") or "(none)"


__all__ = ["SectionChangeError", "slug", "bind_ids", "record_requirement", "executor_for", "apply",
           "pinned", "rerun", "find_named", "names", "MAX_ATTEMPTS"]
