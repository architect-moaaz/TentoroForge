"""Smith composing a screen — by calling the agent that already composes them.

Smith had one write move: rename an element. Asked to build a dashboard it
answered that nothing needed changing, having understood the request perfectly
and had nowhere to put it.

The composer it needed was already there. `page_layouts` composes one page per
subject, through A2UI with the authoring agent behind it, and `apply_change`
already implements §114 steps 3-7 — analyse impact, commit the Blueprint, run
the §72 sub-DAG. Neither was reachable from a conversation. This connects them.

NOTHING NEW COMPOSES ANYTHING HERE. `compose_route` builds the same `TaskSpec`
the orchestrator builds and hands it to the same executor, so a page Smith
composes and a page the build composed come from one code path. A second
composer would be a second answer to "what does this screen look like", and
the first thing to diverge.

AND THE BLUEPRINT STAYS THE RECORD. Both verbs end at `apply_change`, so the
artifact is committed before anything regenerates and the incremental DAG
re-projects from it. A seam that wrote `src/schemas/*.json` directly would
leave the Blueprint describing a different application, which is the
divergence §115 refuses.
"""

from __future__ import annotations

import json
import re

import logging
from pathlib import Path
from typing import Any, Sequence

from services.llm_client import tell

logger = logging.getLogger(__name__)


#: The agent that actually authors a layout — the one `page_layouts` runs, and
#: per AGENT_REGISTRY the only agent permitted to write `pageLayouts` at all.
#:
#: SMITH DID NOT WRITE THIS. Committing under `agent="smith"` was refused by
#: §30's boundary check after a 147-second composition had already succeeded:
#:
#:     CapabilityViolation: agent 'smith' may not write 'pageLayouts' (§30).
#:
#: The refusal is correct and widening Smith's capability to satisfy it would
#: be the wrong repair — a coordinator exempt from the boundary check is §28's
#: uncontrolled swarm with a nicer name. Smith orchestrated; `a2ui_pages`
#: authored; the commit is attributed to the author.
#:
#: One constant for both the TaskSpec and the commit, so the agent that runs
#: and the agent that is credited cannot drift apart — which is the only way
#: this error comes back.
COMPOSER_AGENT = "a2ui_pages"


class ComposeError(RuntimeError):
    """The request named something the Blueprint does not have."""


def _page_for_route(doc: dict, route: str) -> dict | None:
    """The page contract for a route, tolerant about how a user typed it."""
    want = (route or "").strip()
    if not want:
        return None
    if not want.startswith("/"):
        want = "/" + want
    pages = [p for p in (doc.get("pages") or []) if p.get("status") != "DEPRECATED"]

    for page in pages:
        if (page.get("route") or "") == want:
            return page
    # "/dashboard" for a page named Dashboard, "home" for "/" — a user names the
    # screen as often as the path, and refusing on punctuation would be pedantry.
    lowered = want.lstrip("/").lower()
    for page in pages:
        if str(page.get("name") or "").strip().lower() == lowered:
            return page
    if lowered in ("home", "index", "dashboard", ""):
        return next((p for p in pages if (p.get("route") or "") == "/"), None)
    return None


def _name_from_route(route: str) -> str:
    """A human page name from a route: '/client-invoices' -> 'Client Invoices'."""
    tail = (route or "").rstrip("/").rsplit("/", 1)[-1]
    tail = tail.strip("/[]").replace("-", " ").replace("_", " ").strip()
    if not tail:
        return "Home"
    return " ".join(w.capitalize() for w in tail.split())


def _ensure_page(svc: Any, route: str, request: str = "") -> dict:
    """The page contract for `route`, CREATING a minimal one when the
    definition does not have it yet.

    compose_route's own contract is a route that "renders nothing, is empty, or
    404s", and a route the Blueprint has never heard of is the purest case of
    that. The implementation nonetheless REFUSED it (DEFECT C-03/B-09/F-07):
    someone asking for a Clients screen got "there is no page at '/clients' in
    this application" and no way forward, because the only screens Smith could
    compose were the ones the definition already listed. A definition is allowed
    to grow — asking for a screen that isn't there yet is how it grows.

    Deterministic: no model, no LLM. It writes only the four fields the PAGE
    contract requires (`id` is allocated by `upsert`); the composition that
    follows is what gives the page its layout, exactly as it does for a page the
    definition already had. Idempotent — a route that already exists is returned
    untouched, so this never duplicates a page or overwrites its contract.
    """
    existing = _page_for_route(svc.doc, route)
    if existing is not None:
        return existing

    want = (route or "").strip()
    if not want:
        raise ComposeError("no route was named, so there is nothing to compose.")
    if not want.startswith("/"):
        want = "/" + want

    name = _name_from_route(want)
    body = {
        "name": name,
        "route": want,
        # Business-terms purpose is a required field; the request is the closest
        # thing to a stated reason we have, and it reads back sensibly in the
        # definition ("add a screen for clients") until the user refines it.
        # ON ONE LINE. The request now carries the whole ask — the sentence
        # that asked for the screen as well as the answer that placed it — and
        # a purpose is read back in the definition as a phrase, not a
        # transcript.
        "purpose": (" ".join(request.split()) or f"The {name} screen.")[:280],
        "primaryTasks": [],
    }
    # ALLOCATING A NEW ID, unlike every write compose did before — recompose and
    # add_widgets only ever UPDATE a page already in the definition. A new id
    # collides if the allocator registry has fallen behind the document (a
    # Blueprint loaded without its ids.json — an import or a restore). bootstrap
    # binds the document's ids into the registry first; it is idempotent, so it
    # is free when the registry is already in step.
    from services.blueprint.ids import page_key
    from services.smith.smith import bootstrap as _bind_ids
    _bind_ids(svc)
    # THE REGISTRY'S OWN KEY — the one the definition allocates pages under.
    page = svc.upsert("pages", body, natural_key=page_key(want))
    svc.save()
    logger.info("[smith] add_page %s -> %s", want, page.get("id"))
    return page


#: How many times a conversational compose may be asked, matching the DAG's
#: `max_attempts`. One is not enough and the reason is measured: on this
#: application A2UI composed a dashboard carrying `density` on Card — a prop
#: the catalog advertises on Table and not on Card — and the whole turn was
#: lost to it. The DAG would have re-asked with the validator's own message.
MAX_ATTEMPTS = 2


def compose_route(
    svc: Any,
    route: str,
    *,
    app_root: str | None = None,
    request: str = "",
    executor: Any = None,
    reasoning: Any = None,
) -> Any:
    """Compose the screen at `route` and commit it.

    Runs the `page_layouts` agent for exactly that page — the same executor,
    the same TaskSpec, the same A2UI path the build uses — then hands the
    proposals to `apply_change`.

    RE-ASKED WHEN REFUSED, for the same reason the DAG re-asks. `orchestrator`
    catches a rejected apply, records `_reason(exc)` as the subject's feedback
    and runs the node again; every one of those mechanisms is on the DAG path,
    and a conversation reached none of them. So a composition refused for one
    unexpected prop ended the turn — three and a half minutes of composing
    thrown away over a `density` on a Card, with the message that would have
    fixed it going only to a log.

    §102: a retry that is not told what went wrong is the same request again,
    so the feedback rides on the TaskSpec exactly as it does in a run.
    """
    from services.blueprint.agent_contract import InvalidPatternTemplate, AuthorRefusal
    from services.blueprint.executors import make_executor, tiered_router, RunUsage
    from services.blueprint.orchestrator import TaskSpec
    from services.blueprint.service import BlueprintInvalid
    from services.smith.change import apply_change

    # A route the definition does not have yet is created rather than refused —
    # composing a screen that "renders nothing or 404s" is what this verb is
    # FOR (DEFECT C-03/B-09/F-07). `_ensure_page` is idempotent, so an existing
    # route is returned unchanged and only a genuinely new one grows the
    # definition before it is laid out.
    page = _ensure_page(svc, route, request)

    # The composition is the slow part of the turn — around a minute behind a
    # single message. `reasoning` is how that minute becomes legible: the
    # executor's stream was already open and its thinking events discarded.
    run = executor or make_executor(svc, tiered_router(reasoning=reasoning),
                                    usage=RunUsage.for_app(svc, phase="change"),
                                    reasoning=reasoning)
    feedback = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        spec = TaskSpec(task_id=f"smith-compose-{page['id']}-{attempt}",
                        node="page_layouts", agent=COMPOSER_AGENT,
                        attempt=attempt, subject=page["id"],
                        feedback=feedback or None,
                        # THE WORDS THAT ASKED FOR THIS COMPOSITION. A brief
                        # is about this attempt, feedback about the last one;
                        # without it a conversation could recompose a page
                        # forever and never say what it wanted different.
                        brief=request or "")

        tell(reasoning, f"Composing the screen at {page.get('route')}.", "step")
        result = run(spec)
        if not getattr(result, "proposals", None):
            # The composer declining is a real outcome and says so. Reporting
            # it as a success with nothing behind it is the failure this whole
            # module is a reaction to.
            raise ComposeError(
                f"the composer returned nothing for {page.get('route')}. "
                "Nothing has been changed."
            )

        # THE EXECUTOR IS WHAT MAKES THE CHANGE REACH THE APP. `apply_change`
        # runs the §72 sub-DAG only `if run_agents and executor is not None`,
        # and this passed none — so the layout was committed to the Blueprint,
        # the version bumped, the turn reported success, and the frontend was
        # never projected. The route stayed blank. Committing without
        # regenerating is exactly the divergence §115 refuses, arrived at by
        # omitting an argument.
        try:
            return apply_change(
                svc,
                request or f"compose the screen at {page.get('route')}",
                proposals=list(result.proposals),
                interpretation=(f"recompose {page.get('route')} "
                                f"({page.get('pattern')})"),
                agent=COMPOSER_AGENT,
                app_root=app_root,
                executor=_traced(run, reasoning),
            )
        except (BlueprintInvalid, AuthorRefusal) as exc:
            feedback = f"{type(exc).__name__}: {exc}".replace("\n", " ")[:400]
            from services.blueprint.refusals import record_refusal
            record_refusal(svc.output_dir, page["id"], attempt,
                           list(result.proposals), f"{type(exc).__name__}: {exc}")
            if attempt == MAX_ATTEMPTS:
                raise ComposeError(
                    f"the composition of {page.get('route')} was refused "
                    f"{MAX_ATTEMPTS} times and nothing has been changed. "
                    f"The last reason was: {feedback}"
                ) from exc
            tell(reasoning,
                 f"That composition was refused — {feedback} Composing again.",
                 "step")

    raise ComposeError(f"no composition was produced for {page.get('route')}.")


def _traced(executor: Any, reasoning: Any) -> Any:
    """The executor, saying which node it is on.

    Deterministic work, not reasoning — the sub-DAG re-projects the frontend
    from the committed Blueprint. It is the last stretch of a compose turn and
    it was the quiet one: composition reported itself, then the panel went
    still for the part that actually puts the page on disk.

    The same wrapper shape `_run_dag` uses for a full build, so a node reports
    itself identically whether the run came from a build or from a sentence in
    a conversation.
    """
    def _go(spec: Any) -> Any:
        tell(reasoning, f"Regenerating {spec.node}.", "step", spec.node)
        out = executor(spec)
        tell(reasoning, f"{spec.node} done.", "step", spec.node)
        return out

    return _go


def add_widgets(
    svc: Any,
    route: str,
    widgets: Sequence[str],
    *,
    app_root: str | None = None,
    request: str = "",
    executor: Any = None,
    reasoning: Any = None,
) -> Any:
    """Add named sections to a screen, by saying so in its contract first.

    NOT A PATCH ON THE TREE. The page contract is what a composition is written
    from, so the widgets are recorded there — in `primaryTasks`, which is
    already the free-text statement of what a user comes to this page to do —
    and then the page is composed again against the contract that now names
    them.

    Patching the rendered tree instead would put the widgets in the app and
    leave the Blueprint describing a page without them: the next composition
    would drop them, and nobody would know why. Recording intent and
    regenerating is §115, and it is also simply more likely to produce a page
    that hangs together than five components spliced into someone else's
    layout.
    """
    from services.blueprint.service import ARTIFACT_SECTIONS  # noqa: F401

    # Checked before the page is touched: an empty request must not grow the
    # definition with a page nobody asked to fill.
    wanted = [str(w).strip() for w in (widgets or []) if str(w).strip()]
    if not wanted:
        raise ComposeError("no widgets were named, so there is nothing to add.")

    # A route that isn't in the definition is created (with these widgets as its
    # first tasks) rather than refused — same DEFECT C-03/B-09/F-07 fix as
    # compose_route. Idempotent for a route that already exists.
    page = _ensure_page(svc, route, request)

    tasks = list(page.get("primaryTasks") or [])
    added = [w for w in wanted if w not in tasks]
    if added:
        # Committed on its own, before composing. If the composition then fails
        # the contract still records what was asked for, and a retry composes
        # against it rather than starting from a page that never heard the
        # request.
        from services.blueprint.ids import page_key
        body = {k: v for k, v in page.items() if k != "id"}
        body["primaryTasks"] = tasks + added
        # Under the registry's own key: keyed by the bare route, the allocator
        # minted a SECOND page id for the same route (PAGE-003 beside PAGE-002).
        svc.upsert("pages", body, natural_key=page_key(str(page.get("route") or route)))
        svc.save()
        logger.info("[smith] %s primaryTasks += %s", page.get("route"), added)

    return compose_route(
        svc, page.get("route") or route, app_root=app_root,
        request=request or f"add {', '.join(wanted)} to {page.get('route')}",
        executor=executor, reasoning=reasoning,
    )


# ── the tool seam ───────────────────────────────────────────────────────

#: Which verbs this module answers for. `run` is what the agent loop calls, so
#: an unknown verb has to be named rather than silently doing the default —
#: that silence is the whole failure this module exists to remove.
#: What a change request can ask a screen to DO, by the words people use for
#: it, in the page contract's own action vocabulary. Prefix-matched on word
#: boundaries: "delete", "deletion", "deleting"; "remove", "removal".
_CAPABILITY_WORDS: dict[str, tuple[str, ...]] = {
    "delete": ("delet", "remov", "destroy", "archiv"),      # delete/deletion/deleting, remove/removal
    "edit": ("edit", "updat"),
    "create": ("creat", "register", "add new", "new record"),
    "view": ("view record", "open record", "view details", "record details"),
}


def capabilities_named(request: str) -> list[str]:
    import re as _re
    text = (request or "").lower()
    return [verb for verb, words in _CAPABILITY_WORDS.items()
            if any(_re.search(r"\b" + _re.escape(w), text) for w in words)]


def declare_capabilities(svc: Any, page: dict, request: str) -> list[str]:
    """Record in the page contract what the request asks the screen to DO,
    and declare the workflow it needs. Returns the actions added.

    "Add a Delete Record button on each row" went into `primaryTasks` — free
    text the composer reads as a wish — and the page was re-composed with no
    `delete` in its `actions` and no workflow that deletes a Nurse. The
    composer, correctly, left Delete out (the action model says: no delete
    workflow, do not bind Delete to Update), and the turn still reported
    "added Delete Record". A capability is contract, not prose: the verb goes
    into `actions`, the missing CRUD workflow is declared the way the verify
    declares it, and the composition is then held to it — a tree without the
    control is refused, so the reply can only claim what landed.
    """
    entity = str((page.get("data") or {}).get("primaryEntity") or "")
    if not entity:
        return []
    have = {str(a).lower().split("_")[0] for a in (page.get("actions") or []) if isinstance(a, str)}
    added = [v for v in capabilities_named(request) if v not in have]
    if not added:
        return []
    from services.blueprint.ids import page_key
    from services.smith.smith import bootstrap as _bind_ids
    _bind_ids(svc)                        # the registry in step with the document before any allocation
    body = {k: v for k, v in page.items() if k != "id"}
    body["actions"] = list(page.get("actions") or []) + added
    svc.upsert("pages", body, natural_key=page_key(str(page.get("route") or "")))
    svc.save()
    from services.smith.review_gaps import settle_crud_gaps
    settle_crud_gaps(svc, only_pages={str(page.get("id"))})
    # A workflow that already exists for the verb is LAUNCHED FROM this page
    # now — the composer binds only workflows declared to start from a
    # screen, and a removal takes the page off that list, so a later "add it
    # back" must put it on again or the control is composed against a
    # workflow the brief never offered.
    page_id = str(page.get("id") or "")
    ops = {"delete": "db_delete", "edit": "db_update", "create": "db_insert"}
    for w in svc.doc.get("workflows") or []:
        if w.get("status") == "DEPRECATED":
            continue
        step_ops = {str((st.get("config") or {}).get("actionType") or "") for st in w.get("steps") or []}
        on_entity = any(str(st.get("entity")) == entity for st in w.get("steps") or [])
        if on_entity and any(ops.get(v) in step_ops for v in added) and page_id not in (w.get("launchedFrom") or []):
            w["launchedFrom"] = list(w.get("launchedFrom") or []) + [page_id]
    svc.save()
    logger.info("[smith] %s actions += %s", page.get("route"), added)
    return added


def ensure_edit_page(svc: Any, page: dict) -> dict | None:
    """The screen an `edit` needs, created when the definition has none.

    The platform's own rule: a form page whose route carries `[id]` is an
    EDIT screen (one form, pre-filled, submit saves); a form without one is a
    CREATE screen. Med Registration was defined with the create screen only
    — `/nurse-registration` — and `save_edit` declared on it, which one Form
    running one workflow cannot honour. "Implement the edit functionality"
    then re-composed the list, whose Edit already navigated to
    `/nurse-registration/{{id}}`: a route nothing served. The edit lives on
    its own page. Returns the page created, or None when one can already
    host it (an `[id]` form page or a record page for the entity)."""
    entity = str((page.get("data") or {}).get("primaryEntity") or "")
    if not entity:
        return None
    pages = [p for p in (svc.doc.get("pages") or []) if p.get("status") != "DEPRECATED"
             and str((p.get("data") or {}).get("primaryEntity") or "") == entity]
    from services.blueprint.functional_completeness import page_family
    if any(page_family(p) == "record" or (page_family(p) == "form" and "[" in str(p.get("route") or ""))
           for p in pages):
        return None
    create = next((p for p in pages if page_family(p) == "form"), None)
    update = next((w for w in (svc.doc.get("workflows") or [])
                   if any((st.get("config") or {}).get("actionType") == "db_update"
                          for st in w.get("steps") or [])
                   and any(str(st.get("entity")) == entity for st in w.get("steps") or [])), None)
    if create is None or update is None:
        return None                        # nothing to edit with — Page↔Workflow's, not a page's
    ename = next((str(e.get("name")) for e in (svc.doc.get("data") or {}).get("entities") or []
                  if str(e.get("id")) == entity), entity)
    route = str(create.get("route") or "").rstrip("/") + "/[id]"
    from services.blueprint.ids import page_key
    body = {
        "name": f"Edit {ename}", "route": route, "pattern": "form",
        "purpose": f"Change one existing {ename}: the form opens pre-filled with its current values "
                   f"and saving runs {update.get('name') or update.get('id')}.",
        "actions": ["save_edit", "cancel"],
        "data": {"primaryEntity": entity},
        "requirements": list(create.get("requirements") or []),
        "navigatesTo": [str(p["id"]) for p in pages if page_family(p) == "collection" and p.get("id")],
        "primaryTasks": [f"Edit an existing {ename} and save the changes"],
    }
    if create.get("module"):
        body["module"] = create["module"]
    if create.get("users"):
        body["users"] = list(create["users"])
    new_page = svc.upsert("pages", body, natural_key=page_key(route))
    # The list reaches it, and the update workflow is launchable from it —
    # the composer binds only workflows declared to start from a screen.
    for p in svc.doc.get("pages") or []:
        if page_family(p) == "collection" and str((p.get("data") or {}).get("primaryEntity") or "") == entity:
            nav = list(p.get("navigatesTo") or [])
            if new_page["id"] not in nav:
                p["navigatesTo"] = nav + [new_page["id"]]
    launched = list(update.get("launchedFrom") or [])
    if new_page["id"] not in launched:
        update["launchedFrom"] = launched + [new_page["id"]]
    svc.save()
    logger.info("[smith] created the edit screen %s (%s) for %s", route, new_page["id"], ename)
    return new_page


def prepare_capabilities(svc: Any, route: str, request: str, *, app_root: str | None = None,
                         executor: Any = None, reasoning: Any = None) -> dict:
    """Before EITHER compose verb runs: what the request asks the screen to
    DO becomes contract (`declare_capabilities`), and an edit gets the screen
    it needs (`ensure_edit_page`), composed first so the list's Edit has
    somewhere to go. Lives on the one entry point both verbs share — wired
    into `add_widgets` alone, "implement the edit functionality" went through
    `compose_route` and none of it happened."""
    page = _page_for_route(svc.doc, route)
    if page is None:
        return {"declared": [], "created": []}
    declared = declare_capabilities(svc, page, request)
    created: list[str] = []
    if "edit" in capabilities_named(request):
        page = _page_for_route(svc.doc, route) or page
        edit_page = ensure_edit_page(svc, page)
        if edit_page is not None:
            created.append(str(edit_page["route"]))
            tell(reasoning, f"There was no screen to edit a record on — creating "
                            f"{edit_page.get('route')} first.", "step")
            compose_route(svc, edit_page["route"], app_root=app_root,
                          request=f"compose the edit screen at {edit_page['route']}",
                          executor=executor, reasoning=reasoning)
    return {"declared": declared, "created": created}


VERBS = ("compose_route", "add_widgets")


#: Below this a word is too common to say anything about whether a particular
#: thing was composed — "add", "row", "the". A curated list of such words is
#: the exception list this codebase has been burned by; a length is one rule
#: with nothing to maintain, and being wrong about it leaves a claim
#: unchecked rather than contradicting a true one.
MIN_DISTINCTIVE = 5


def _distinctive(widget: str) -> str:
    """The longest word of a widget ask, lowercased, or "" when it has none
    worth looking for. An identifier survives whole ("fathersname"), which is
    what makes it the most specific thing the ask contains."""
    words = [w.lower() for w in re.findall(r"[A-Za-z][A-Za-z0-9]*", widget or "")]
    longest = max(words, key=len, default="")
    return longest if len(longest) >= MIN_DISTINCTIVE else ""


def unshown(svc: Any, route: str, wanted: Sequence[str]) -> list[str]:
    """The asked widgets the page's live layout does not contain.

    The composer is TOLD what to add and is free to lay the page out without
    it — it did exactly that with a "Father's Name (fathersName) input field",
    and the reply said "added". A widget counts as shown when its longest
    word appears anywhere in the layout — a label, a binding, a column key.
    An ask with no long word is left unchecked rather than guessed at.
    """
    page = _page_for_route(svc.doc, route)
    if page is None:
        return []
    layouts = [l for l in (svc.doc.get("pageLayouts") or [])
               if isinstance(l, dict) and str(l.get("page")) == str(page.get("id"))
               and l.get("status") not in ("SUPERSEDED", "DEPRECATED")]
    if not layouts:
        return [str(w) for w in wanted]
    hay = json.dumps(layouts[-1].get("root") or {}).lower()
    missing = []
    for w in wanted:
        word = _distinctive(str(w))
        if word and word not in hay:
            missing.append(str(w))
    return missing


def _field_named(svc: Any, route: str, widget: str) -> tuple[dict, dict] | None:
    """The page's primary entity and the field a widget ask names, or None.

    "Father's Name (fathersName) input field" names `Nurse.fathersName`; a
    "recent activity" section names nothing. Matched on the field's name as
    an identifier, or on its name spelled out as words.
    """
    page = _page_for_route(svc.doc, route)
    if page is None:
        return None
    eid = str((page.get("data") or {}).get("primaryEntity") or "")
    ent = next((e for e in ((svc.doc.get("data") or {}).get("entities") or [])
                if isinstance(e, dict) and str(e.get("id")) == eid), None)
    if ent is None:
        return None
    low = " " + re.sub(r"[^a-z0-9]+", " ", (widget or "").lower()) + " "
    idents = {w.lower() for w in re.findall(r"[A-Za-z][A-Za-z0-9]*", widget or "")}
    # THE MOST SPECIFIC FIELD WINS. "Father's Name (fathersName) input field"
    # names `fathersName`; it also contains the word "name", and `name` is a
    # field too. Taking the first match put the wrong field on the form.
    hits: list[dict] = []
    for f in ent.get("fields") or []:
        fname = str((f or {}).get("name") or "")
        if not fname or (f or {}).get("primaryKey"):
            continue
        words = " " + " ".join(re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", fname).lower().split()) + " "
        if fname.lower() in idents or (len(words.strip()) >= 4 and words in low):
            hits.append(f)
    if not hits:
        return None
    return ent, max(hits, key=lambda f: len(str(f.get("name") or "")))


# ---------------------------------------------------------------------------
# A page written as React
# ---------------------------------------------------------------------------
#
# THE SCREEN IS ITS CODE. A page the UI engineer wrote renders from its
# `pageCode` row; its `pageLayouts` tree is the fallback nobody sees. Composing
# the tree changed nothing on screen: "add an age × gender heatmap to the
# dashboard" laid a Heatmap node into the tree, the rebuild had no page to
# write, and the check that looked at the real screen said so (h7gmi93x). So a
# coded page is changed the way the build writes it — the analytics agent
# declares what the ask needs to count, the UI engineer rewrites the page
# around it — and both land as one change.

WIDGET_ATTEMPTS = 2

#: Pages the analytics agent's own rule gives no widgets: "a form, a wizard, a
#: settings page or a tool carries none". Told only "Open A Dispute page has
#: nothing in it", the agent filled a dispute FORM with three dashboard charts
#: (036farqu) — so on these pages it is not asked at all unless the person
#: named a number or a chart themselves.
NO_ANALYTICS_PATTERNS = frozenset({"form", "wizard", "settings", "configuration"})
#: Pages whose job IS numbers: rebuilt with none yet, their charts are designed
#: even when the ask names none ("this dashboard looks empty").
NUMBERS_PATTERNS = frozenset({"dashboard", "analytics", "command_center"})


def code_row(doc: dict, page_id: str) -> dict | None:
    """The page's React code, or None when it renders from its layout."""
    return next((r for r in doc.get("pageCode") or []
                 if isinstance(r, dict) and str(r.get("page")) == str(page_id)
                 and str(r.get("view") or "").strip()), None)


def _widget_brief(page: dict, request: str, wanted: Sequence[str]) -> str:
    asks = "".join(f"\n- {w}" for w in wanted)
    return (f"The person asked, about the page {page.get('route')} ({page.get('id')}, a "
            f"`{page.get('pattern') or 'page'}` page — {page.get('purpose') or 'no stated purpose'}): "
            f"\"{request}\"{asks}\n\n"
            f"Declare ONLY the widgets this ask adds or changes, all on page {page.get('id')} — "
            "a KPI, a chart, a breakdown — and only when the ask is for something counted or "
            "charted. A page that looks empty or wrong is the page's code to fix, not a place "
            "to put charts: never add a widget to fill space. Every other widget stays exactly "
            "as it is and is not returned. When the ask needs nothing counted or charted, "
            "return no proposal.")


def _declare_widgets(svc: Any, page: dict, request: str, wanted: Sequence[str], *,
                     run: Any, reasoning: Any) -> list[Any]:
    """The widget proposals the ask needs on `page`, held to the query rules
    the editor holds a chart to; re-asked with what was wrong."""
    from services.blueprint.orchestrator import TaskSpec
    from services.blueprint.verification import _query_findings

    ents = {str(e.get("id")): e for e in (svc.doc.get("data") or {}).get("entities") or []}
    ents.update({str(e.get("name")): e for e in ents.values()})
    feedback = ""
    for attempt in range(1, WIDGET_ATTEMPTS + 1):
        tell(reasoning, f"Deciding what {page.get('route')} should count for: {request}.", "step")
        result = run(TaskSpec(task_id=f"smith-widgets-{page['id']}-{attempt}", node="analytics",
                              agent="analytics", attempt=attempt, feedback=feedback or None,
                              brief=_widget_brief(page, request, wanted)))
        props = [p for p in (getattr(result, "proposals", None) or []) if p.section == "widgets"]
        problems: list[str] = []
        for prop in props:
            body = prop.body
            body.setdefault("page", page["id"])
            if str(body.get("page")) != str(page["id"]):
                problems.append(f"{body.get('label')}: belongs on {page['id']}, not {body.get('page')}")
                continue
            src = body.get("dataSource") or {}
            ent = ents.get(str(src.get("entity")))
            if src.get("op") == "query" and ent is not None:
                problems += [f"{body.get('label')}: {f}" for f in _query_findings(body, src, ent)]
        if not problems:
            return props
        feedback = "Refused — fix every one of these:\n" + "\n".join(f"- {x}" for x in problems)
        tell(reasoning, f"That chart was refused — {problems[0][:160]}. Asking again.", "step")
    raise ComposeError(f"the chart for {page.get('route')} could not be defined: {feedback}")


def _with_widgets(doc: dict, props: Sequence[Any]) -> dict:
    """The document as it will be once `props` land — what the page is written
    against, so the SDK it compiles with already has the new widgets."""
    import copy
    out = copy.deepcopy(doc)
    rows = out.setdefault("widgets", [])
    for i, prop in enumerate(props):
        body = dict(prop.body)
        body.setdefault("id", str(prop.natural_key or f"WIDGET-NEW-{i}"))
        at = next((k for k, w in enumerate(rows) if str(w.get("id")) == str(body["id"])), None)
        if at is None:
            rows.append(body)
        else:
            rows[at] = {**rows[at], **body}
    return out


def _into_menu(svc: Any, page: dict, app_root: str | None = None) -> None:
    """A page the owner asked for is somewhere they expect to find: first in
    the menu, and — at "/" — where the application opens."""
    nav = svc.doc.setdefault("navigation", {})
    tree = nav.setdefault("tree", [])
    if not any(isinstance(n, dict) and str(n.get("page")) == str(page.get("id")) for n in tree):
        tree.insert(0, {"label": str(page.get("name") or page.get("route")), "page": page.get("id"),
                        "icon": "home" if page.get("route") == "/" else "layout-grid"})
    if page.get("route") == "/":
        init = nav.get("initialRoute") if isinstance(nav.get("initialRoute"), dict) else {}
        nav["initialRoute"] = {**init, "default": "/", "authenticated": "/"}
    svc.save()
    if app_root:
        from services.blueprint.projection import project_shell
        project_shell(svc.doc, app_root)


def coded_app(doc: dict) -> bool:
    """Whether this application's pages are written as React code."""
    return any(isinstance(r, dict) and r.get("view") for r in doc.get("pageCode") or [])


def _where(svc: Any, route: str) -> str:
    """A page as a person finds it: its name, its address, and whether the
    menu leads there. "composed /" was the whole reply once, and the person
    looked for the change on the page they thought of — "built the discover
    page it is not there" (UAT jubyt8jk)."""
    page = _page_for_route(svc.doc, route) or {}
    name = str(page.get("name") or "").strip()
    label = ""

    def walk(nodes: Any) -> None:
        nonlocal label
        for n in nodes or []:
            if isinstance(n, dict):
                if str(n.get("page") or "") == str(page.get("id") or "-") and not label:
                    label = str(n.get("label") or "")
                walk(n.get("children"))

    walk(((svc.doc.get("navigation") or {}).get("tree")))
    where = f"**{name}** (`{route}`)" if name else f"`{route}`"
    if label:
        return f"{where}, which the menu calls “{label}”"
    # A ONE-RECORD PAGE IS NOT MISSING FROM THE MENU. "/tools/[id]" is opened
    # by picking a row on its list; saying it is not in the menu read as a
    # fault in what had just been done (UAT replay 3).
    if "[" in route:
        parent = _page_for_route(svc.doc, route.rsplit("/", 1)[0]) or {}
        opened = f", opened from **{parent['name']}**" if parent.get("name") else ""
        return f"{where} — one record's page{opened}"
    return f"{where} — it is not in the menu; open it at `{route}`"


def recode_page(svc: Any, route: str, *, app_root: str, request: str,
                wanted: Sequence[str] = (), executor: Any = None, client: Any = None,
                reasoning: Any = None) -> dict:
    """Change a coded page: its new widgets, then its code, as one change.

    Returns `{applied, committed, version, reason, missing}` — `missing` the
    asked-for widgets the new code does not draw, read off the code itself.
    """
    from services.blueprint.agent_contract import AgentResult, ArtifactProposal, apply_agent_result
    from services.blueprint.app_sdk import project_code_pages, widget_keys
    from services.blueprint.executors import RunUsage, make_executor, tiered_router
    from services.blueprint.ui_engineer import CompileError, compose_page, ensure_sdk

    page = _page_for_route(svc.doc, route)
    row = code_row(svc.doc, str((page or {}).get("id")))
    # In an application whose pages are code, a page with none yet is WRITTEN
    # as code (no current version) — it went to the layout composer, took
    # seven minutes for "/", and came back a layout in a coded app.
    if page is None or (row is None and not coded_app(svc.doc)):
        raise ComposeError(f"{route} is not a page written as code.")
    usage = RunUsage.for_app(svc, phase="change")
    run = executor or make_executor(svc, tiered_router(reasoning=reasoning), usage=usage, reasoning=reasoning)
    # CHARTS ONLY WHEN CHARTS WERE ASKED FOR. Understanding the ask names the
    # widgets it wants (`wanted`); with none, the analytics author was still
    # asked what the page "should count" — "change the heading" came back as
    # four new KPI tiles, or as charts for other pages that were refused and
    # failed the edit after four minutes (0l133sp2).
    has_widgets = any(str(w.get("page")) == str(page.get("id")) and w.get("status") != "DEPRECATED"
                      for w in svc.doc.get("widgets") or [] if isinstance(w, dict))
    numbers_page = str(page.get("pattern") or "") in NUMBERS_PATTERNS
    # A FIELD TO SHOW IS NOT A CHART. "Show the product name", "show the
    # description more prominently" arrive as widgets that ARE a field's name;
    # handed to the analytics author they came back as six KPI tiles and a
    # rentals-over-time chart (UAT replay 3). Only the exact name counts — a
    # "age × gender heatmap" mentions fields and is still a chart.
    fields = {str(f.get("name") or "").lower() for e in (svc.doc.get("data") or {}).get("entities") or []
              if isinstance(e, dict) for f in e.get("fields") or [] if isinstance(f, dict)}
    charted = [w for w in wanted if w.strip().lower() not in fields]
    if not charted and (wanted or has_widgets or not numbers_page):
        widgets: list[Any] = []
    else:
        widgets = _declare_widgets(svc, page, request, charted, run=run, reasoning=reasoning)
    doc = _with_widgets(svc.doc, widgets)
    root = Path(app_root)
    try:
        ensure_sdk(doc, root)
        tell(reasoning, f"Rewriting {route} with what was asked.", "step")
        brief = request + "".join(f"\n- {w}" for w in wanted)
        if widgets:
            keys = widget_keys(doc)
            brief += ("\n\nDraw these new widgets, each with `WidgetView` from the page's `runWidget` data: "
                      + ", ".join(f"widgets.{keys.get(str(w.body.get('id')), '?')} ({w.body.get('label')})"
                                  for w in widgets))
        llm = client or tiered_router(reasoning=reasoning).for_task("page_code", "ui_engineer")
        try:
            body, spent = compose_page(doc, page, root, llm, brief=brief, current=row, node="page_code")
        except CompileError as exc:
            raise ComposeError(f"the new {route} did not compile, so nothing was changed: {exc}") from exc
        for u, elapsed in spent:
            usage.record(node="page_code", agent="ui_engineer", usage=u, elapsed_s=elapsed)
        # EACH SECTION BY THE AGENT THAT OWNS IT (§30) — the widgets are the
        # analytics agent's, the code the UI engineer's — and ONE commit for
        # both, so the change is one version and one undo. `apply_change`
        # versions only what reports artifacts, and a `pageCode` row reports
        # none: a code-only change through it was saved with no version at
        # all, and an undo could not reach it.
        before = svc.snapshot()
        committed: list[str] = []
        steps = [("analytics", list(widgets))] if widgets else []
        steps.append(("ui_engineer", [ArtifactProposal(section="pageCode", natural_key=str(page["id"]), body=body)]))
        for agent, proposals in steps:
            application = apply_agent_result(svc, AgentResult(
                task_id=f"TASK-smith-recode-{page['id']}-{agent}", agent=agent,
                proposals=proposals, confidence=1.0), commit=False)
            if not application.applied:
                svc.doc = before
                svc.save()
                return {"applied": False, "committed": [], "version": int(svc.doc.get("version") or 0),
                        "reason": application.reason or "the change was refused", "missing": []}
            committed += list(application.artifacts or [])
        record = svc.commit(
            user_request=request or f"change {route}",
            smith_interpretation=(f"rewrite {route}" + (
                f", adding {', '.join(str(w.body.get('label')) for w in widgets)}" if widgets else "")),
            before=before, affected=sorted(set(committed) | {str(page["id"])}))
        version = int(record["version"])
    finally:
        # The SDK as the document has it, whichever way this went.
        ensure_sdk(svc.doc, root)
    project_code_pages(svc.doc, root)
    # SHOWN MEANS DRAWN: a new widget counts when the new view reads it.
    keys = widget_keys(svc.doc)
    view = str(body.get("view") or "")
    declared = {str(w.body.get("label")) for w in widgets}
    missing = [str(w.get("label")) for w in svc.doc.get("widgets") or []
               if str(w.get("label")) in declared and f"widgets.{keys.get(str(w.get('id')))}" not in view]
    # A FIELD ASKED FOR IS CHECKED BY ITS NAME; a layout ask is not guessed
    # at. The check took a "distinctive" word from each ask and searched the
    # code for it: "Tools grid — nearby available tools…" was reported as not
    # shown on a page rewritten as a grid, because "nearby" is not in its
    # source (UAT replay). What cannot be checked is not claimed missing.
    def norm(x: Any) -> str:
        return re.sub(r"[^a-z0-9]", "", str(x or "").lower())

    fields = {norm(f.get("name")): str(f.get("name")) for e in (svc.doc.get("data") or {}).get("entities") or []
              for f in e.get("fields") or [] if isinstance(f, dict) and f.get("name")}
    for w in wanted:
        name = fields.get(norm(w))
        if name and name not in view:
            missing.append(w)
    return {"applied": True, "committed": committed, "version": version,
            "reason": "", "missing": missing, "widgets": sorted(declared)}


def run(output_dir: str, verb: str, *, route: str = "",
        widgets: Sequence[str] = (), request: str = "",
        reasoning: Any = None) -> dict:
    """One composition, from an `output_dir` — the shape a tool handler needs.

    THE ONLY ENTRY POINT WITH BOTH CALLERS ON IT. The ReAct loop dispatches by
    tool name and `smith_session.run_iteration` dispatches by verb; if each
    loaded the Blueprint and called `apply_change` its own way there would be
    two answers to "what does composing a route do", which is the defect shape
    this session has spent its time removing. Both go through here.

    Returns the `{applied, edited_paths, ...}` envelope the other write tools
    return. A refusal is `applied: False` with a `reason` — never an exception
    that the loop would render as "unknown error" and never a bare success.
    """
    from services.blueprint.service import BlueprintService

    try:
        svc = BlueprintService.load(output_dir=str(output_dir))
    except FileNotFoundError:
        return {"applied": False, "edited_paths": [],
                "reason": ("this project has no Blueprint yet, so there is no "
                           "screen to compose. It needs defining first.")}

    app_root = str(Path(output_dir) / "app")
    wanted = [str(w).strip() for w in (widgets or []) if str(w).strip()]
    if verb not in VERBS:
        return {"applied": False, "edited_paths": [],
                "reason": f"unknown compose verb {verb!r}; "
                          f"expected one of {', '.join(VERBS)}"}
    try:
        prepared = prepare_capabilities(svc, route, f"{request} {' '.join(wanted)}",
                                        app_root=app_root, reasoning=reasoning)
    except ComposeError as exc:
        return {"applied": False, "edited_paths": [], "reason": str(exc)}
    except Exception as exc:  # noqa: BLE001 — a tool degrades, it does not crash
        logger.exception("[smith] preparing %s for %s failed", route, verb)
        return {"applied": False, "edited_paths": [], "reason": f"{type(exc).__name__}: {exc}"}
    extra = "".join(
        ([f"; declared {', '.join(prepared['declared'])} on it"] if prepared["declared"] else [])
        + ([f"; created the edit screen {', '.join(prepared['created'])}"] if prepared["created"] else []))
    page = _page_for_route(svc.doc, route)
    # A NEW PAGE IN A CODED APP IS WRITTEN AS CODE TOO. It went to the layout
    # composer (seven minutes), whose tree the frontend then dropped — "I laid
    # out Home" about a page that was not served: "built the discover page it
    # is not there" (UAT jubyt8jk). Declared, put in the menu, then written.
    if page is None and verb == "compose_route" and coded_app(svc.doc):
        page = _ensure_page(svc, route, request)
        _into_menu(svc, page, app_root)
    if page is not None and (code_row(svc.doc, str(page.get("id"))) is not None or coded_app(svc.doc)):
        try:
            out = recode_page(svc, route, app_root=app_root, request=request, wanted=wanted,
                              reasoning=reasoning)
        except ComposeError as exc:
            return {"applied": False, "edited_paths": [], "reason": str(exc)}
        except Exception as exc:  # noqa: BLE001 — a tool degrades, it does not crash
            logger.exception("[smith] rewriting %s failed", route)
            return {"applied": False, "edited_paths": [], "reason": f"{type(exc).__name__}: {exc}"}
        added = out.get("widgets") or []
        did = (f"I rewrote {_where(svc, route)}{extra}"
               + (f", adding {', '.join(added)}" if added else "")
               + (f", but the new screen does not show {', '.join(out['missing'])}" if out["missing"] else "")
               + ".")
        return {"applied": out["applied"], "edited_paths": out["committed"],
                "diff_summary": did, "version": out["version"], "reason": out["reason"],
                "missing": out["missing"]}
    # A FIELD THE ENTITY ALREADY HAS NEEDS NO COMPOSER. "Show fathersName on
    # the registration page" asks for a control on a form, and the form is in
    # the layout; putting it there is deterministic. The composer, asked the
    # same thing, re-laid the page out and left the field off it.
    # Either verb: "I cannot see fathersName on the registration page" is
    # read as a recompose as often as an add, and both mean the same thing
    # when the words name a field the entity has.
    if verb in ("add_widgets", "compose_route"):
        from services.smith.field_change import show_field, summary_of
        shown: list[dict] = []
        rest: list[str] = []
        asks = list(wanted) if verb == "add_widgets" else ([request] if _field_named(svc, route, request) else [])
        for w in asks:
            hit = _field_named(svc, route, w)
            if hit is None:
                rest.append(w)
                continue
            ent, fld = hit
            page = _page_for_route(svc.doc, route) or {}
            try:
                out = show_field(svc, str(ent.get("name") or ""), str(fld.get("name") or ""),
                                 page_id=str(page.get("id") or "") or None,
                                 app_root=app_root, reasoning=reasoning)
            except Exception as exc:  # noqa: BLE001 — falls through to the composer
                logger.warning("[smith] could not surface %s on %s: %s", w, route, exc)
                rest.append(w)
                continue
            if out.get("applied"):
                shown.append(out)
            else:
                rest.append(w)
        if shown and not rest:
            paths = sorted({p for o in shown for p in (o.get("edited_paths") or [])})
            return {"applied": True, "edited_paths": paths,
                    "diff_summary": "\n\n".join(summary_of("show_field", o) for o in shown),
                    "version": int(svc.doc.get("version") or 0), "reason": "", "missing": []}
        if verb == "add_widgets":
            wanted = rest
    try:
        if verb == "add_widgets":
            result = add_widgets(svc, route, wanted, app_root=app_root,
                                 request=request, reasoning=reasoning)
            did = f"I added {', '.join(wanted)} to {_where(svc, route)}{extra}"
        elif verb == "compose_route":
            result = compose_route(svc, route, app_root=app_root,
                                   request=request, reasoning=reasoning)
            did = f"I laid out {_where(svc, route)} again{extra}"
    except ComposeError as exc:
        # The composer declining is a real outcome and says so.
        return {"applied": False, "edited_paths": [], "reason": str(exc)}
    except Exception as exc:  # noqa: BLE001 — a tool degrades, it does not crash
        logger.exception("[smith] %s %s failed", verb, route)
        return {"applied": False, "edited_paths": [],
                "reason": f"{type(exc).__name__}: {exc}"}

    # `committed` is what `apply_change` actually reports. An earlier caller
    # read `artifacts`, which ChangeResult does not have, so every successful
    # composition reported nothing changed.
    committed = sorted(getattr(result, "committed", None) or [])
    missing = unshown(svc, route, wanted) if verb == "add_widgets" else []
    if missing:
        did = (f"re-composed {route}{extra}, but the new screen does not show "
               f"{', '.join(missing)}")
    return {
        "applied": bool(getattr(result, "applied", False)),
        "edited_paths": committed,
        "diff_summary": did + (f" — {len(committed)} artifact(s)"
                               if committed else ""),
        "version": getattr(result, "version", 0),
        "reason": str(getattr(result, "reason", "") or ""),
        "missing": missing,
    }
