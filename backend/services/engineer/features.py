"""Features: what the engineer builds one at a time.

A feature is a module the person approved at the model review — "Product
Catalogue", "Cart & Checkout" — the slice they would recognise. Modules are
ordered by dependence: a module whose records point at another module's
records (an order's `customerId`) comes after it. Each node of the build then
has a part that belongs to the feature — the page subjects whose pages are
its, the processes its pages launch, the statement groups about its
requirements — so the authoring nodes run for one feature at a time, with
the rest of the app already built and proven behind them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

#: The feature that stands in when the definition has no modules.
WHOLE = "the application"


@dataclass
class Feature:
    id: str
    name: str
    pages: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    requirements: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return self.name or self.id


def _live(rows: Any) -> list[dict]:
    return [r for r in rows or [] if isinstance(r, dict) and r.get("status") != "DEPRECATED"]


def features(doc: Mapping[str, Any]) -> list[Feature]:
    """The approved modules as features, in order of dependence. A page in
    no module joins the module its primary entity's other pages are in, else
    a last feature of its own. An auth page belongs to none (the build
    declares those whole). A deferred module is left out."""
    from services.blueprint.scope import deferred_page_ids, module_of_page

    pages = [p for p in _live(doc.get("pages")) if p.get("id") and p.get("pattern") != "auth"]
    held = deferred_page_ids(doc)
    pages = [p for p in pages if str(p["id"]) not in held]
    owner = module_of_page(doc)
    modules = [m for m in _live(doc.get("modules")) if m.get("id") and not m.get("deferred")]
    by_id: dict[str, Feature] = {str(m["id"]): Feature(id=str(m["id"]), name=str(m.get("name") or m["id"]))
                                 for m in modules}
    rest = Feature(id="MODULE-REST", name="the rest of the application")
    entity_home: dict[str, str] = {}
    for p in pages:
        pid = str(p["id"])
        mod = owner.get(pid)
        primary = str((p.get("data") or {}).get("primaryEntity") or "")
        if mod in by_id:
            by_id[mod].pages.append(pid)
            if primary:
                entity_home.setdefault(primary, mod)
    for p in pages:
        pid = str(p["id"])
        if owner.get(pid) in by_id:
            continue
        primary = str((p.get("data") or {}).get("primaryEntity") or "")
        home = by_id.get(entity_home.get(primary, ""))
        (home or rest).pages.append(pid)
    out = [f for f in by_id.values() if f.pages] + ([rest] if rest.pages else [])
    if not by_id or not out:
        out = [Feature(id="MODULE-ALL", name=WHOLE, pages=[str(p["id"]) for p in pages])]
    page_by_id = {str(p["id"]): p for p in pages}
    for f in out:
        ents: list[str] = []
        reqs: list[str] = []
        for pid in f.pages:
            data = page_by_id[pid].get("data") or {}
            for e in [data.get("primaryEntity"), *(data.get("supportingEntities") or [])]:
                if e and str(e) not in ents:
                    ents.append(str(e))
            for r in page_by_id[pid].get("requirements") or []:
                if r and str(r) not in reqs:
                    reqs.append(str(r))
        f.entities, f.requirements = ents, reqs
    return _ordered(out, doc)


def _ordered(feats: list[Feature], doc: Mapping[str, Any]) -> list[Feature]:
    """Dependence first: a feature whose entities reference another feature's
    entities comes after it; otherwise the modules' own order."""
    owner_of_entity: dict[str, str] = {}
    for f in feats:
        for e in f.entities:
            owner_of_entity.setdefault(e, f.id)
    refs: dict[str, set[str]] = {f.id: set() for f in feats}
    entities = {str(e.get("id")): e for e in _live((doc.get("data") or {}).get("entities"))}
    for f in feats:
        for eid in f.entities:
            for fld in (entities.get(eid) or {}).get("fields") or []:
                target = str((fld or {}).get("references") or "")
                other = owner_of_entity.get(target)
                if other and other != f.id:
                    refs[f.id].add(other)
    done: list[Feature] = []
    left = list(feats)
    while left:
        ready = [f for f in left if refs[f.id] <= {d.id for d in done}]
        if not ready:
            ready = [left[0]]                      # a cycle: the modules' order decides
        done.append(ready[0])
        left.remove(ready[0])
    return done


#: The statement group about the people (sign-in, landings): the first
#: feature's, since every later one signs in through what it proves.
PEOPLE_GROUP = "people"


def subjects_of(feature: Feature, node: str, doc: Mapping[str, Any], pending: list[str],
                *, first: bool) -> list[str]:
    """Of a node's `pending` subjects, the ones that belong to `feature`.
    A node that runs once for the app (`[""]`) is left as it is — its call
    is given the feature as a brief instead (`brief_for`)."""
    from services.blueprint.orchestrator import DAG, page_subjects

    fanout = DAG[node].fanout if node in DAG else ""
    if not fanout:
        return pending
    mine = set(feature.pages)
    if fanout == "pages":
        return [s for s in pending if s in mine]
    if fanout == "page_features":
        groups = page_subjects(doc)
        return [s for s in pending if {str(p.get("id")) for p in groups.get(s, [])} & mine]
    if fanout == "entities":
        return [s for s in pending if s in set(feature.entities)]
    if fanout == "workflows":
        return [s for s in pending if s in set(workflows_of(feature, doc))]
    if fanout == "expectation_groups":
        from services.expects.statements import expect_subjects
        groups = expect_subjects(dict(doc))
        wanted = set(feature.requirements)
        out = []
        for s in pending:
            if s == PEOPLE_GROUP:
                if first:
                    out.append(s)
                continue
            reqs = set((groups.get(s) or {}).get("requirements") or [])
            if reqs and len(reqs & wanted) * 2 >= len(reqs):
                out.append(s)
        return out
    return pending


def workflows_of(feature: Feature, doc: Mapping[str, Any]) -> list[str]:
    """The declared processes a feature's pages launch — a process is
    written with the screens that start it — or, when nothing launches one,
    the feature whose records it takes."""
    mine = set(feature.pages)
    ents = set(feature.entities)
    out: list[str] = []
    for w in _live(doc.get("workflows")):
        if not w.get("id"):
            continue
        launched = {str(p) for p in w.get("launchedFrom") or []}
        if launched & mine or (not launched and any(
                str(i.get("entity") or "") in ents for i in w.get("inputs") or [] if isinstance(i, dict))):
            out.append(str(w["id"]))
    return out


def statements_of(feature: Feature, doc: Mapping[str, Any]) -> list[str]:
    """The statements about the feature: those whose requirements are its,
    plus every statement that moves through one of its screens or processes."""
    wanted = set(feature.requirements)
    mine = set(feature.pages)
    flows = set(workflows_of(feature, doc))
    out: list[str] = []
    for st in _live(doc.get("expectations")):
        if not st.get("id"):
            continue
        reqs = {str(r) for r in st.get("requirements") or []}
        pages = {str(s.get("page")) for s in st.get("steps") or [] if isinstance(s, dict) and s.get("page")}
        procs = {str(s.get("workflow")) for s in st.get("steps") or [] if isinstance(s, dict) and s.get("workflow")}
        # Its requirements say whose it is; a statement that cites none is
        # placed by the screens it moves through, then by the processes.
        if reqs:
            its = reqs <= wanted
        elif pages:
            its = pages <= mine
        else:
            its = bool(procs) and procs <= flows
        if its:
            out.append(str(st["id"]))
    return out


def brief_for(feature: Feature, node: str, doc: Mapping[str, Any]) -> str:
    """What a node that runs once for the app is told when it is run for one
    feature: write this feature's part, keep the others' as they are."""
    from services.blueprint.orchestrator import DAG
    if node in DAG and DAG[node].fanout:
        return ""
    pages = {str(p.get("id")): p for p in _live(doc.get("pages"))}
    named = ", ".join(f"{pages[p].get('name') or p} ({pages[p].get('route') or ''})"
                      for p in feature.pages if p in pages)
    return (f"THIS CALL IS FOR ONE FEATURE: {feature.label}, whose screens are {named or 'none yet'}. "
            f"Write what this feature needs and nothing for the others — a process one of these screens "
            f"launches, a rule over these records ({', '.join(feature.entities) or 'none'}), a chart on "
            f"these screens. Everything already written for other features stays exactly as it is; "
            f"return it unchanged if the reply must carry it.")


__all__ = ["Feature", "features", "subjects_of", "workflows_of", "statements_of", "brief_for", "WHOLE"]
