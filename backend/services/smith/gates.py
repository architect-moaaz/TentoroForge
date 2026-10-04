"""The two reviews before a build: the requirements, then the product model.

A person agrees to an application twice, and each time to something they can
judge in a sentence. First WHAT IT MUST DO — the requirements, grouped by what
the product does. Then WHAT IT IS MADE OF — its modules, and in each the
screens, records, processes and connections that will be generated. Each gate
is a conversation that loops until they say yes: they ask for a change, Smith
makes it and shows what moved, and asks again.

WHERE THE STATE LIVES. The gate is §94's state (BLUEPRINT_REVIEW is the
requirements, PLAN_REVIEW the product model) and the answer is §95's approval
record (`understanding`, then `blueprint`) — both already in the Blueprint.
What this adds is memory of what each round showed: every version a person
was shown is kept beside the Blueprint (`.forge/gates/<gate>.json`), so a
round can say "added 1, removed 2, changed 1" instead of making them read
fourteen requirements again. Versions are a record of the conversation, not
part of the definition, which is why they are not a Blueprint section.

WHO CHANGES WHAT. Smith interprets the message and briefs the owner: a
requirement is redrafted by the requirements agent, a screen by the page
designer, a record by the data modeller, a module by the architect. Retiring,
moving and renaming — the edits that are the same whatever the domain — are
applied here, because asking a model to restate a list with one line missing
is how the other lines drift.
"""
from __future__ import annotations

import contextlib
import copy
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from services.llm_client import tell

logger = logging.getLogger(__name__)

REQUIREMENTS = "requirements"
PRODUCT_MODEL = "product_model"

#: §95's gate each review answers.
APPROVAL_GATE = {REQUIREMENTS: "understanding", PRODUCT_MODEL: "blueprint"}

#: The parts of a product model a change can touch, and the node that owns
#: each. A change is briefed only to the owners of the parts it touches.
PART_NODE: dict[str, str] = {
    "modules": "ux_architecture",
    "records": "data_model",
    "screens": "page_contracts",
    "roles": "security",
    "connections": "integrations",
}


def _live(rows: Any) -> list[dict]:
    return [r for r in (rows or []) if isinstance(r, dict) and r.get("status") != "DEPRECATED"]


def is_built(output_dir: str | Path) -> bool:
    """The same signal the router uses: the generated app's package.json."""
    return (Path(output_dir) / "app" / "package.json").is_file()


def current(doc: Mapping[str, Any], output_dir: str | Path) -> str | None:
    """Which review the application is waiting on, or None.

    Read off §94's state: PLANNING is the model being drafted (or a draft that
    stopped part way), which is the product model's review to show; the states
    up to BLUEPRINT_REVIEW are the requirements'. A built application is past
    both."""
    if is_built(output_dir):
        return None
    state = str(doc.get("state") or "")
    if state in ("PLANNING", "PLAN_REVIEW"):
        return PRODUCT_MODEL
    if state in ("DISCOVERY", "CLARIFICATION", "DEFINITION", "BLUEPRINT_REVIEW") \
            and _live(doc.get("requirements")):
        return REQUIREMENTS
    return None


# ---------------------------------------------------------------------------
# What each gate shows
# ---------------------------------------------------------------------------

def requirement_items(doc: Mapping[str, Any]) -> list[dict]:
    """The live requirements as the review shows them, in document order."""
    out = []
    for r in _live(doc.get("requirements")):
        out.append({
            "id": str(r.get("id") or ""),
            "description": str(r.get("description") or ""),
            "area": str(r.get("area") or "").strip(),
            "criteria": [str(c) for c in r.get("acceptanceCriteria") or []],
            "assumption": str(r.get("assumption") or ""),
        })
    return out


def _entity_home(doc: Mapping[str, Any], module_pages: dict[str, list[dict]]) -> dict[str, str]:
    """``{entity id: module id}`` — the module whose screens are mostly ABOUT
    that record. A record no screen is about is shared."""
    votes: dict[str, dict[str, int]] = {}
    for mid, pages in module_pages.items():
        for p in pages:
            eid = str((p.get("data") or {}).get("primaryEntity") or "")
            if eid:
                votes.setdefault(eid, {}).setdefault(mid, 0)
                votes[eid][mid] += 1
    return {eid: max(by.items(), key=lambda kv: kv[1])[0] for eid, by in votes.items()}


def model_view(doc: Mapping[str, Any]) -> dict:
    """The product model, module by module — what will be generated, each part
    with one line on what it is for.

    Membership is read off the references the parts already carry (a page's
    `module`, a page's primary record, a workflow's launching pages) rather
    than stored twice: a page moved between modules moves everything that
    follows it."""
    from services.blueprint.scope import module_of_page

    pages = _live(doc.get("pages"))
    owner = module_of_page(doc)
    modules = _live(doc.get("modules"))
    module_ids = {str(m.get("id")) for m in modules}
    by_module: dict[str, list[dict]] = {str(m.get("id")): [] for m in modules}
    auth: list[dict] = []
    loose: list[dict] = []
    for p in pages:
        if p.get("pattern") == "auth":
            auth.append(p)
            continue
        mid = owner.get(str(p.get("id")))
        (by_module[mid] if mid in module_ids else loose).append(p)

    entities = _live((doc.get("data") or {}).get("entities"))
    home = _entity_home(doc, by_module)
    page_module = {str(p.get("id")): mid for mid, ps in by_module.items() for p in ps}

    def page_row(p: dict) -> dict:
        return {"id": str(p.get("id") or ""), "name": str(p.get("name") or p.get("route") or ""),
                "route": str(p.get("route") or ""), "purpose": str(p.get("purpose") or ""),
                "pattern": str(p.get("pattern") or "")}

    def entity_row(e: dict) -> dict:
        return {"id": str(e.get("id") or ""), "name": str(e.get("name") or ""),
                "description": str(e.get("description") or ""),
                "fields": [str(f.get("name")) for f in e.get("fields") or []
                           if isinstance(f, dict) and f.get("name")]}

    def workflow_row(w: dict) -> dict:
        return {"id": str(w.get("id") or ""), "name": str(w.get("name") or ""),
                "purpose": str(w.get("purpose") or ""),
                "trigger": str((w.get("trigger") or {}).get("kind") or "")}

    workflows = _live(doc.get("workflows"))
    wf_home: dict[str, str] = {}
    for w in workflows:
        homes = [page_module[str(pid)] for pid in w.get("launchedFrom") or [] if str(pid) in page_module]
        if homes:
            wf_home[str(w.get("id"))] = max(set(homes), key=homes.count)

    out_modules = []
    for m in modules:
        mid = str(m.get("id"))
        mine = by_module.get(mid, [])
        covers = sorted({str(r) for p in mine for r in p.get("requirements") or []})
        out_modules.append({
            "id": mid,
            "name": str(m.get("name") or mid),
            "description": str(m.get("description") or ""),
            "deferred": bool(m.get("deferred")),
            "pages": [page_row(p) for p in mine],
            "entities": [entity_row(e) for e in entities if home.get(str(e.get("id"))) == mid],
            "workflows": [workflow_row(w) for w in workflows if wf_home.get(str(w.get("id"))) == mid],
            "requirements": covers,
        })

    integrations = [{"id": str(i.get("id") or ""), "name": str(i.get("name") or ""),
                     "kind": str(i.get("kind") or ""), "provider": str(i.get("provider") or ""),
                     "connected": bool(i.get("serves"))}
                    for i in _live(doc.get("integrations"))]
    roles = [{"id": str(r.get("id") or ""), "name": str(r.get("name") or ""),
              "description": str(r.get("description") or "")} for r in _live(doc.get("roles"))]
    if not roles:
        roles = [{"id": "", "name": str(p.get("name") or ""), "description": str(p.get("description") or "")}
                 for p in (doc.get("product") or {}).get("personas") or [] if isinstance(p, dict)]

    cited = {str(r) for p in pages for r in p.get("requirements") or []} \
        | {str(r) for w in workflows for r in w.get("requirements") or []} \
        | {str(r) for e in entities for r in e.get("requirements") or []}
    reqs = [r["id"] for r in requirement_items(doc)]
    return {
        "modules": out_modules,
        "foundation": {
            "roles": roles,
            "auth": [page_row(p) for p in auth],
            "pages": [page_row(p) for p in loose],
            "entities": [entity_row(e) for e in entities if str(e.get("id")) not in home],
            "workflows": [workflow_row(w) for w in workflows if str(w.get("id")) not in wf_home],
        },
        "integrations": integrations,
        # Only meaningful once something cites requirements; before that every
        # requirement would read as uncovered, which is not what it means.
        "uncovered": [r for r in reqs if r not in cited] if cited else [],
        "counts": {"modules": len(out_modules), "pages": len(pages), "entities": len(entities),
                   "workflows": len(workflows), "integrations": len(integrations),
                   "roles": len(roles)},
    }


# ---------------------------------------------------------------------------
# Versions — what each round showed
# ---------------------------------------------------------------------------

def _store(output_dir: str | Path, gate: str) -> Path:
    return Path(output_dir) / ".forge" / "gates" / f"{gate}.json"


def versions(output_dir: str | Path, gate: str) -> list[dict]:
    try:
        data = json.loads(_store(output_dir, gate).read_text("utf-8"))
    except (OSError, ValueError):
        return []
    rows = data.get("versions") if isinstance(data, dict) else None
    return [v for v in rows or [] if isinstance(v, dict)]


def snapshot(doc: Mapping[str, Any], gate: str) -> Any:
    return requirement_items(doc) if gate == REQUIREMENTS else model_view(doc)


def record_version(output_dir: str | Path, gate: str, doc: Mapping[str, Any], *,
                   request: str = "") -> dict:
    """Keep what the person is about to be shown. A round that changed nothing
    is not a new version — "v3" beside an identical "v2" reads as a change."""
    rows = versions(output_dir, gate)
    items = snapshot(doc, gate)
    if rows and rows[-1].get("items") == items:
        return rows[-1]
    row = {"version": (int(rows[-1].get("version") or 0) + 1) if rows else 1,
           "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "request": request, "items": items}
    rows.append(row)
    path = _store(output_dir, gate)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"versions": rows}, indent=1, ensure_ascii=False), "utf-8")
    return row


def requirements_diff(before: list[dict], after: list[dict]) -> dict:
    was = {r["id"]: r for r in before}
    now = {r["id"]: r for r in after}
    changed = []
    for rid, r in now.items():
        old = was.get(rid)
        if old and (old["description"] != r["description"] or old.get("area") != r.get("area")
                    or old.get("criteria") != r.get("criteria")):
            changed.append({"id": rid, "was": old["description"]})
    return {"added": [rid for rid in now if rid not in was],
            "removed": [dict(was[rid]) for rid in was if rid not in now],
            "changed": changed}


def _parts(module: dict) -> dict[str, str]:
    """``{kind:id: name}`` for everything a module holds."""
    out = {}
    for kind in ("pages", "entities", "workflows"):
        for part in module.get(kind) or []:
            out[f"{kind}:{part.get('id')}"] = str(part.get("name") or "")
    return out


def model_diff(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict:
    was = {m["id"]: m for m in before.get("modules") or []}
    now = {m["id"]: m for m in after.get("modules") or []}
    changed = []
    for mid, m in now.items():
        old = was.get(mid)
        if not old:
            continue
        a, b = _parts(old), _parts(m)
        added = [k for k in b if k not in a]
        removed = [{"key": k, "name": a[k]} for k in a if k not in b]
        renamed = old.get("name") != m.get("name")
        if added or removed or renamed or old.get("description") != m.get("description"):
            changed.append({"id": mid, "added": added, "removed": removed,
                            **({"was": old.get("name")} if renamed else {})})
    ints_was = {i["id"] for i in before.get("integrations") or []}
    ints_now = {i["id"] for i in after.get("integrations") or []}
    return {"added": [mid for mid in now if mid not in was],
            "removed": [{"id": mid, "name": was[mid].get("name")} for mid in was if mid not in now],
            "changed": changed,
            "integrations": {"added": sorted(ints_now - ints_was), "removed": sorted(ints_was - ints_now)}}


def diff(gate: str, before: Any, after: Any) -> dict:
    return requirements_diff(before or [], after or []) if gate == REQUIREMENTS \
        else model_diff(before or {}, after or {})


def payload(doc: Mapping[str, Any], output_dir: str | Path) -> dict:
    """Everything the review panel draws, in one read.

    Both gates are returned whichever is open: the product model's review
    shows the approved requirements beside it, and a built application still
    shows its modules — including the ones waiting to be built."""
    from services.blueprint import approval

    out: dict[str, Any] = {"gate": current(doc, output_dir), "built": is_built(output_dir)}
    for gate in (REQUIREMENTS, PRODUCT_MODEL):
        rows = versions(output_dir, gate)
        items = snapshot(doc, gate)
        last = rows[-1] if rows else None
        prev = rows[-2] if len(rows) > 1 else None
        shown = last["items"] if last else None
        out[gate] = {
            "version": int(last["version"]) if last else (1 if items else 0),
            "items": items,
            # Against the version before the one on screen, so the diff is
            # "what my last message did", not "what changed since v1".
            "diff": diff(gate, prev["items"], shown) if prev and shown == items else None,
            "approval": approval.state_of(dict(doc), APPROVAL_GATE[gate]),
        }
    return out


# ---------------------------------------------------------------------------
# One turn at a gate
# ---------------------------------------------------------------------------

TURN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["kind", "answer", "brief", "parts", "remove", "move", "rename", "newRequirements",
                 "requirementsChange", "reword"],
    "properties": {
        "kind": {"type": "string", "enum": ["change", "question", "approve", "other"]},
        "answer": {"type": "string", "description": "for a question: the answer, briefly"},
        "brief": {"type": "string", "description": (
            "for a change: what to add or reword, restated precisely for the specialist who "
            "makes it, naming existing items by id. Empty when the change is only retiring, "
            "moving or renaming.")},
        "parts": {"type": "array", "items": {"type": "string", "enum": sorted(PART_NODE)},
                  "description": "product model only: which parts the brief adds to or rewords"},
        "remove": {"type": "array", "items": {"type": "string"},
                   "description": "ids of items the change retires"},
        "move": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["page", "module"],
            "properties": {"page": {"type": "string"}, "module": {"type": "string"}}},
            "description": "product model only: screens moved to another module"},
        "rename": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["id", "name"],
            "properties": {"id": {"type": "string"}, "name": {"type": "string"}}}},
        "newRequirements": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["description", "area"],
            "properties": {"description": {"type": "string"}, "area": {"type": "string"}}},
            "description": ("product model only: behaviour the change adds that no approved "
                            "requirement covers, each as one testable statement")},
        "reword": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["id", "description"],
            "properties": {"id": {"type": "string"}, "description": {"type": "string"}}},
            "description": ("existing requirements the change rewords: the id, and the whole "
                            "requirement as it should now read")},
        "requirementsChange": {"type": "string", "description": (
            "product model only: when the person rewords or retires an APPROVED requirement, "
            "that change restated for the requirements' author, naming the requirement by id. "
            "Empty otherwise.")},
    },
}

_WHAT = {
    REQUIREMENTS: ("the requirements — what the application must do, before anything is designed",
                   "Retire a requirement by listing its id in `remove`. When the change alters what an "
                   "existing requirement says, put it in `reword` with its id and its whole new "
                   "wording — never restate it as a new one. Only requirements that do not exist "
                   "yet go in `brief`. Leave `parts`, `move` and `newRequirements` empty."),
    PRODUCT_MODEL: ("the product model — the application's modules and, in each, the screens, "
                    "records, processes and connections that will be generated",
                    "Retire items by id in `remove` (a module, screen, record, connection or role; "
                    "retiring a record retires the screens that exist only to show it — list those "
                    "too). Move screens between modules with `move`; merging two modules is moving "
                    "every screen of one into the other and retiring the empty one. Rename with "
                    "`rename`. Anything added or reworded goes in `brief`, with `parts` naming "
                    "which parts it touches. When the change adds behaviour none of the approved "
                    "requirements states, add it to `newRequirements`. When it rewords or retires "
                    "an approved requirement, put the new wording in `reword` (or a retirement in "
                    "`remove`), and put what it means for the model in `brief` and `parts`."),
}


def _client() -> Any:
    from services.blueprint.executors import AGENT_MODEL, AnthropicModel
    return AnthropicModel(model=AGENT_MODEL, effort="medium")


def interpret(doc: Mapping[str, Any], gate: str, message: str, history: list[tuple[str, str]] = (),
              *, client: Any = None) -> dict:
    """What the person's message is, at this gate: a change (and to what), a
    question (and its answer), an approval, or something else for Smith's
    ordinary turn — connecting a design, a colour, a general ask."""
    what, rules = _WHAT[gate]
    shown: Any = requirement_items(doc) if gate == REQUIREMENTS else model_view(doc)
    context = {"application": (doc.get("application") or {}).get("name", ""), "shown": shown}
    if gate == PRODUCT_MODEL:
        context["approvedRequirements"] = requirement_items(doc)
    system = (f"You are Smith, reviewing {what} with the person who asked for the application. "
              "They are looking at exactly what is under `shown`. Decide what their latest message is.\n"
              "- `change`: they want something in it different.\n"
              "- `question`: they are asking about it — answer from what is shown, in two or three "
              "plain sentences, and do not change anything.\n"
              "- `approve`: they accept it as it stands.\n"
              "- `other`: anything that is not about what is shown.\n"
              f"{rules}\nUse only ids that appear in what is shown. Every field is required; use "
              "empty strings and empty lists for what does not apply.")
    recent = "\n".join(f"{role}: {text}" for role, text in list(history)[-6:] if text)
    user = (("Recent conversation:\n" + recent + "\n\n" if recent else "")
            + f"Their message: {message!r}\n\nWhat they are looking at:\n"
            + json.dumps(context, indent=1, ensure_ascii=False))
    raw = (client or _client())(system=system, user=user, schema=TURN_SCHEMA)
    try:
        data = json.loads(str(getattr(raw, "text", raw)))
    except ValueError:
        return {"kind": "other"}
    return data if isinstance(data, dict) else {"kind": "other"}


# ---------------------------------------------------------------------------
# Making the change
# ---------------------------------------------------------------------------

class GateChangeError(Exception):
    """Nothing could be changed, with a reason the person can act on."""


@contextlib.contextmanager
def _all_or_nothing(svc: Any):
    """A change at a review lands whole or not at all. Its steps commit as
    they go (a retirement, then the owner's redraft), so a redraft refused
    after a retirement would leave half the change in the document and a
    reply saying nothing changed."""
    kept = copy.deepcopy(svc.doc)
    try:
        yield
    except Exception:
        from services.smith.section_change import bind_ids
        svc.doc.clear()
        svc.doc.update(kept)
        svc.save()
        bind_ids(svc)
        raise


def _retire(svc: Any, ids: list[str]) -> list[str]:
    """Mark each named artifact DEPRECATED, wherever it lives. Returns the
    names of what was retired."""
    wanted = {str(i) for i in ids if i}
    gone: list[str] = []
    sections = [svc.doc.get(s) or [] for s in
                ("requirements", "modules", "pages", "integrations", "roles", "workflows")]
    sections.append((svc.doc.get("data") or {}).get("entities") or [])
    for rows in sections:
        for row in rows:
            if isinstance(row, dict) and str(row.get("id")) in wanted and row.get("status") != "DEPRECATED":
                row["status"] = "DEPRECATED"
                gone.append(str(row.get("name") or row.get("description") or row.get("id")))
    return gone


#: The field each section's identity is read from (`ids.natural_key_for`).
_IDENTITY_FIELD = {"requirements": "description", "data.entities": "name"}


def carry_ids(svc: Any, rows: list[tuple[str, Mapping[str, Any]]]) -> None:
    """Keep each artifact's id across a change of the text its identity is
    read from — a reworded requirement, a renamed record.

    Identity is read off the artifact (a requirement's prose, a record's
    name), so rewording one is, to the allocator, a new artifact claiming an
    id that belongs to the old one, and the write is refused. Smith is the one
    that judges it is the same artifact reworded — the person asked for this
    change to it — so the new wording is written onto the artifact first and
    the registry re-read from the document, which keys the id by it."""
    from services.smith.section_change import bind_ids

    moved = False
    for section, body in rows:
        field = _IDENTITY_FIELD.get(section)
        aid = str(body.get("id") or "")
        text = body.get(field) if field else None
        if not (field and aid and isinstance(text, str) and text.strip()):
            continue
        pool = (svc.doc.get("data") or {}).get("entities") if section == "data.entities" \
            else svc.doc.get(section)
        for row in pool or []:
            if isinstance(row, dict) and str(row.get("id")) == aid and row.get(field) != text:
                row[field] = text
                moved = True
    if moved:
        bind_ids(svc)


def _reword(svc: Any, rewords: list[dict]) -> list[str]:
    """Existing requirements, reworded in place — same id, new text.

    Applied here rather than asked of the requirements agent: told that a
    reworded requirement keeps its id, it wrote a second requirement beside
    the first (live, 2026-09-27: "capture country, state and city" left
    REQ-001 and a new REQ-009 saying the same with a location). Rewording is
    the same edit whatever the domain, like retiring or renaming."""
    live = {str(r.get("id")): r for r in _live(svc.doc.get("requirements"))}
    done = []
    for rw in rewords:
        row = live.get(str(rw.get("id") or ""))
        text = str(rw.get("description") or "").strip()
        if row is not None and text and row.get("description") != text:
            row["description"] = text
            done.append(str(row.get("id")))
    if done:
        from services.smith.section_change import bind_ids
        bind_ids(svc)   # the reworded text is the requirement's identity now; same id
    return done


def _rename(svc: Any, renames: list[dict]) -> list[str]:
    done = []
    by_id = {str(r.get("id")): str(r.get("name") or "").strip() for r in renames if r.get("name")}
    sections = [("modules", svc.doc.get("modules")), ("pages", svc.doc.get("pages")),
                ("data.entities", (svc.doc.get("data") or {}).get("entities")),
                ("integrations", svc.doc.get("integrations")), ("roles", svc.doc.get("roles"))]
    for section, rows in sections:
        for row in rows or []:
            if isinstance(row, dict) and str(row.get("id")) in by_id and row.get("name") != by_id[str(row["id"])]:
                done.append(f"{row.get('name')} → {by_id[str(row['id'])]}")
                row["name"] = by_id[str(row["id"])]
    if done:
        from services.smith.section_change import bind_ids
        bind_ids(svc)   # a renamed record is keyed by its new name, same id
    return done


def _move(svc: Any, moves: list[dict]) -> list[str]:
    modules = {str(m.get("id")) for m in _live(svc.doc.get("modules"))}
    done = []
    for mv in moves:
        pid, mid = str(mv.get("page") or ""), str(mv.get("module") or "")
        if mid not in modules:
            continue
        for p in svc.doc.get("pages") or []:
            if isinstance(p, dict) and str(p.get("id")) == pid and p.get("module") != mid:
                p["module"] = mid
                done.append(str(p.get("name") or pid))
        for m in svc.doc.get("modules") or []:
            if isinstance(m, dict) and pid in (m.get("pages") or []) and str(m.get("id")) != mid:
                m["pages"] = [x for x in m["pages"] if x != pid]
    return done


def _commit(svc: Any, request: str, interpretation: str, before: Any) -> None:
    svc.validate()
    svc.commit(user_request=request, smith_interpretation=interpretation, before=before, affected=[])


def _rerun(svc: Any, node: str, brief: str, request: str, *, executor: Any, reasoning: Any,
           sections: tuple[str, ...]) -> int:
    """Brief the owning node; how many artifacts it wrote. An owner with
    nothing to add for this change is not a failure — the change may not
    touch its part after all."""
    from services.smith.section_change import SectionChangeError, rerun
    try:
        props, _ = rerun(svc, node, brief=brief, request=request,
                         interpretation=f"revise at the review gate: {request}",
                         keep=lambda ps: _kept(svc, ps, sections),
                         executor=executor, reasoning=reasoning, empty=_NOTHING_TO_ADD)
    except SectionChangeError as exc:
        if str(exc).endswith(_NOTHING_TO_ADD):
            return 0
        raise GateChangeError(str(exc)) from exc
    return len(props)


def _kept(svc: Any, proposals: list, sections: tuple[str, ...]) -> list:
    """The owner's reply, held to the sections this change may write, with
    every artifact that kept its id carried across its reworded identity."""
    kept = [p for p in proposals if p.section in sections]
    live: dict[str, set[str]] = {
        "requirements": {str(r.get("id")) for r in _live(svc.doc.get("requirements"))},
        "data.entities": {str(e.get("id")) for e in _live((svc.doc.get("data") or {}).get("entities"))},
    }
    carry_ids(svc, [(p.section, p.body) for p in kept
                    if str(p.body.get("id") or "") in live.get(p.section, set())])
    return kept


#: What `rerun` is told to say when an owner returned nothing for its part.
_NOTHING_TO_ADD = "this part had nothing to add for the change"


_REVISE_REQUIREMENTS = (
    "The person is reviewing the requirements and asked for this change:\n\n{brief}\n\n"
    "Return only the NEW requirements this change calls for — ones no existing requirement "
    "states. The existing ones it alters have already been reworded; do not restate any of "
    "them. Give every requirement you return an `area` that matches the area names already in "
    "use where it belongs to one of them.")


def revise_requirements(svc: Any, brief: str, *, remove: list[str] = (), reword: list[dict] = (),
                        request: str = "", executor: Any = None, reasoning: Any = None) -> dict:
    """Redraft the requirements for one change, and say what moved."""
    output_dir = svc.output_dir
    before_items = requirement_items(svc.doc)
    if not versions(output_dir, REQUIREMENTS):
        record_version(output_dir, REQUIREMENTS, svc.doc)
    request = request or brief
    with _all_or_nothing(svc):
        if remove or reword:
            before = svc.snapshot()
            retired = _retire(svc, [r for r in remove if str(r).startswith("REQ")])
            reworded = _reword(svc, list(reword))
            if retired or reworded:
                _commit(svc, request, "retire or reword requirements at the review gate", before)
        if brief.strip():
            tell(reasoning, "Redrafting the requirements.", "step")
            _rerun(svc, "requirements", _REVISE_REQUIREMENTS.format(brief=brief), request,
                   executor=executor, reasoning=reasoning, sections=("requirements",))
    after_items = requirement_items(svc.doc)
    change = requirements_diff(before_items, after_items)
    row = record_version(output_dir, REQUIREMENTS, svc.doc, request=request)
    return {"version": int(row["version"]), "diff": change}


_REVISE_PART = {
    "records": ("The person is reviewing the product model and asked for this change:\n\n{brief}\n\n"
                "Return only the records (entities) this change adds or rewords, each with the "
                "relationships it takes part in. Leave every other record out of your reply."),
    "screens": ("The person is reviewing the product model and asked for this change:\n\n{brief}\n\n"
                "Return only the pages this change adds or rewords; a reworded page keeps its "
                "`route`. Every page names its `module`. Leave every other page out of your reply."),
    "modules": ("The person is reviewing the product model and asked for this change:\n\n{brief}\n\n"
                "Return only the modules this change adds or rewords, and the navigation as it "
                "should be after it."),
    "roles": ("The person is reviewing the product model and asked for this change:\n\n{brief}\n\n"
              "Return only the roles and permissions this change adds or rewords."),
    "connections": ("The person is reviewing the product model and asked for this change:\n\n{brief}\n\n"
                    "Return only the integrations this change adds or rewords."),
}

#: What each owner's reply may write back for a model change.
_PART_SECTIONS: dict[str, tuple[str, ...]] = {
    "records": ("data.entities", "data.relationships"),
    "screens": ("pages",),
    "modules": ("modules", "navigation"),
    "roles": ("roles", "permissions", "security"),
    "connections": ("integrations",),
}


def revise_model(svc: Any, turn: Mapping[str, Any], *, request: str = "", executor: Any = None,
                 reasoning: Any = None, detail: Callable[[Any], Any] | None = None) -> dict:
    """Make one change to the product model, and say what moved.

    `detail` finishes records a change added (their fields), because the
    page set is decided knowing what each record holds; the router passes
    the DAG's own `entity_fields` run."""
    output_dir = svc.output_dir
    before_view = model_view(svc.doc)
    if not versions(output_dir, PRODUCT_MODEL):
        record_version(output_dir, PRODUCT_MODEL, svc.doc)
    request = request or str(turn.get("brief") or "")
    added_reqs: list[str] = []
    reworded: dict | None = None

    with _all_or_nothing(svc):
        # A reworded requirement is redrafted where requirements are, and
        # stays approved — the person changed it themselves, in this message.
        # The model follows it through the brief below.
        rewording = str(turn.get("requirementsChange") or "").strip()
        if rewording or turn.get("reword"):
            from services.blueprint import approval
            was_approved = approval.is_approved(svc.doc, APPROVAL_GATE[REQUIREMENTS])
            reworded = revise_requirements(svc, rewording, reword=list(turn.get("reword") or []),
                                           request=request, executor=executor, reasoning=reasoning)
            if was_approved:
                approval.record(svc, APPROVAL_GATE[REQUIREMENTS],
                                note=f"changed while reviewing the model: {request}")

        # New behaviour is a requirement first: the approved list stays the one
        # statement of what the application must do. The person asked for it in
        # this sentence, so it joins the approved list rather than reopening it.
        new_reqs = [r for r in turn.get("newRequirements") or []
                    if isinstance(r, dict) and str(r.get("description") or "").strip()]
        if new_reqs:
            from services.blueprint import approval
            from services.smith.section_change import record_requirement
            was_approved = approval.is_approved(svc.doc, APPROVAL_GATE[REQUIREMENTS])
            for r in new_reqs:
                row = record_requirement(svc, str(r["description"]).strip(), owner="")
                if not row.get("owner"):
                    row.pop("owner", None)
                if str(r.get("area") or "").strip():
                    row["area"] = str(r["area"]).strip()
                added_reqs.append(str(row.get("id")))
            svc.save()
            if was_approved:
                approval.record(svc, APPROVAL_GATE[REQUIREMENTS], note=f"added while changing the model: {request}")

        before = svc.snapshot()
        retired = _retire(svc, list(turn.get("remove") or []))
        moved = _move(svc, list(turn.get("move") or []))
        renamed = _rename(svc, list(turn.get("rename") or []))
        if retired or moved or renamed:
            _commit(svc, request, "retire, move or rename at the product-model gate", before)

        brief = str(turn.get("brief") or "").strip()
        parts = [p for p in PART_NODE if p in (turn.get("parts") or [])]
        if brief and not parts:
            parts = ["screens"]
        wrote = 0
        for part in parts:  # PART_NODE is in the graph's order
            tell(reasoning, f"Changing the {part}.", "step")
            wrote += _rerun(svc, PART_NODE[part], _REVISE_PART[part].format(brief=brief), request,
                            executor=executor, reasoning=reasoning, sections=_PART_SECTIONS[part])
            if part == "records" and detail is not None:
                detail(svc)
    if added_reqs:
        record_version(output_dir, REQUIREMENTS, svc.doc, request=request)
    after_view = model_view(svc.doc)
    change = model_diff(before_view, after_view)
    row = record_version(output_dir, PRODUCT_MODEL, svc.doc, request=request)
    return {"version": int(row["version"]), "diff": change, "requirements": added_reqs,
            "reworded": reworded, "retired": retired, "moved": moved, "renamed": renamed,
            "wrote": wrote}


# ---------------------------------------------------------------------------
# What Smith says
# ---------------------------------------------------------------------------

def _count(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def ask_line(gate: str) -> str:
    return ("Anything else to change, or shall I lock these in and work out what the app is made of?"
            if gate == REQUIREMENTS else
            "Anything else to change? When it looks right, build the whole app or pick the modules to build first.")


def say_requirements(doc: Mapping[str, Any]) -> str:
    items = requirement_items(doc)
    areas = sorted({r["area"] for r in items if r["area"]})
    assumed = [r for r in items if r["assumption"]]
    lead = (f"Here is what the app needs to do: **{_count(len(items), 'requirement')}**"
            + (f" in {_count(len(areas), 'area')}" if areas else "") + ".")
    if assumed:
        lead += (f" I guessed at **{len(assumed)}** of them (marked *assumed*), so check those first.")
    # STATED UP FRONT, NOT ASKED: every app is the same responsive web app with
    # a phone wrapper, so "which framework?" has no answer the build can honour.
    from services.smith.clarify_brief import WEB_AND_PHONE
    return lead + "\n\n" + WEB_AND_PHONE + "\n\n" + ask_line(REQUIREMENTS)


def say_requirements_change(change: Mapping[str, Any], version: int) -> str:
    bits = []
    if change.get("added"):
        bits.append(f"added {len(change['added'])}")
    if change.get("removed"):
        bits.append(f"removed {len(change['removed'])}")
    if change.get("changed"):
        bits.append(f"changed {len(change['changed'])}")
    if not bits:
        return ("I looked again and nothing needed to change for that — tell me which requirement "
                "you mean if I missed it.\n\n" + ask_line(REQUIREMENTS))
    return f"Done. v{version} " + ", ".join(bits) + ".\n\n" + ask_line(REQUIREMENTS)


def say_model(doc: Mapping[str, Any]) -> str:
    view = model_view(doc)
    c = view["counts"]
    names = [m["name"] for m in view["modules"]]
    lead = (f"Here is the whole app in **{_count(c['modules'], 'module')}**"
            + (f" — {', '.join(names)}" if names else "") + ": "
            + ", ".join(x for x in (_count(c["pages"], "screen"), _count(c["entities"], "record"),
                                    _count(c["integrations"], "connection") if c["integrations"] else "")
                        if x) + ".")
    if view["uncovered"]:
        lead += f" {_count(len(view['uncovered']), 'requirement')} is not covered yet: {', '.join(view['uncovered'])}."
    return lead + "\n\n" + ask_line(PRODUCT_MODEL)


def say_model_change(out: Mapping[str, Any]) -> str:
    change = out.get("diff") or {}
    bits = []
    if change.get("added"):
        bits.append(_count(len(change["added"]), "new module"))
    if change.get("removed"):
        bits.append("retired " + ", ".join(str(m.get("name")) for m in change["removed"]))
    for m in change.get("changed") or []:
        n_add, n_rem = len(m.get("added") or []), len(m.get("removed") or [])
        if n_add or n_rem:
            bits.append(f"{m.get('id')}: " + ", ".join(x for x in (f"+{n_add}" if n_add else "",
                                                                  f"−{n_rem}" if n_rem else "") if x))
    if out.get("moved"):
        bits.append("moved " + ", ".join(out["moved"]))
    if out.get("renamed"):
        bits.append("renamed " + ", ".join(out["renamed"]))
    ints = change.get("integrations") or {}
    if ints.get("added"):
        bits.append(_count(len(ints["added"]), "new connection"))
    rq = (out.get("reworded") or {}).get("diff") or {}
    rq_bits = [f"{k} {len(rq[k])}" for k in ("added", "removed", "changed") if rq.get(k)]
    if not bits and not out.get("requirements") and not rq_bits:
        return ("I looked again and nothing in the model needed to change for that — say which "
                "module or screen you mean if I missed it.\n\n" + ask_line(PRODUCT_MODEL))
    text = (f"Done — model v{out.get('version')}: " + "; ".join(bits) + "." if bits
            else "Done.")
    if rq_bits:
        text += (f"\n\nThe requirements changed with it (v{out['reworded']['version']}: "
                 + ", ".join(rq_bits) + ") and stay approved — you asked for it.")
    if out.get("requirements"):
        text += (f"\n\nThat is new behaviour, so I added {', '.join(out['requirements'])} to the "
                 "approved requirements.")
    return text + "\n\n" + ask_line(PRODUCT_MODEL)


__all__ = [
    "APPROVAL_GATE", "GateChangeError", "PART_NODE", "PRODUCT_MODEL", "REQUIREMENTS",
    "current", "diff", "interpret", "is_built", "model_diff", "model_view", "payload",
    "record_version", "requirement_items", "requirements_diff", "revise_model",
    "revise_requirements", "say_model", "say_model_change", "say_requirements",
    "say_requirements_change", "versions",
]
