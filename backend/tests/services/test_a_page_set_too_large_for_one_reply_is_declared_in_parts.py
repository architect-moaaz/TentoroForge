"""A page set too large for one reply is declared a module at a time.

`page_contracts` answered every slot in one call. Each drawn screen is a page
with a route, a pattern, a module, sections and access — a few hundred output
tokens — so a design of five hundred screens asked one reply for more than its
budget, and a reply cut off is a page set with no pages. Past forty drawn
screens the set is now asked for in parts: one per module the screens were
drawn in (and parts of a large module), side by side, plus one for the rest of
the application. A part that lands is kept, and a resumed build declares only
the parts still missing.
"""
import pytest

from services.blueprint.agent_contract import (
    AgentResult, ArtifactProposal, DrawnScreensShareARoute, check_drawn_routes,
)
from services.blueprint.executors import CACHE_BREAK, build_prompt
from services.blueprint.observer import _rows
from services.blueprint.orchestrator import DAG, completed_nodes, pending_subjects, run, subjects_for
from services.blueprint.page_planner import (
    FEATURES_PART, SCREENS_PER_CALL, drawn_address, page_set_part_of, page_set_parts,
)
from services.blueprint.service import BlueprintService

GROUPS = 10


def _svc(tmp_path, *, screens=500, treat="specification"):
    svc = BlueprintService.create(output_dir=str(tmp_path), app_id="bank", name="Bank",
                                  domain="finance", description="a bank for small businesses")
    svc.doc["designSources"] = [{
        "id": "FIGMA-001", "type": "figma", "fileKey": "A", "url": "https://www.figma.com/design/A/a",
        "name": "Bank", "treatAs": treat,
        "frames": [{"nodeId": f"{i}:1", "name": f"Frame {i}", "shows": f"Screen {i}",
                    "group": f"Area {i % GROUPS}"} for i in range(screens)],
    }]
    svc.doc["modules"] = [{"id": f"MODULE-{g + 1:03d}", "name": f"Area {g}", "designGroup": f"Area {g}",
                           "status": "PROPOSED"} for g in range(GROUPS)]
    svc.doc["data"] = {"entities": [{"id": "ENTITY-001", "name": "Account", "table": "accounts",
                                     "fields": [{"name": "id", "type": "uuid", "primaryKey": True}]}]}
    svc.save()
    return svc


def _pages_for(svc, subject):
    """What a page-set call answers: one page per drawn slot, under its address."""
    parts = page_set_parts(svc.doc)
    address = drawn_address(svc.doc, subject)
    if subject == FEATURES_PART:
        bodies = [{"name": "Accounts", "route": "/accounts", "pattern": "entity_list", "purpose": "accounts",
                   "access": "authenticated", "data": {"primaryEntity": "ENTITY-001"}}]
    else:
        bodies = [{"name": s["shows"], "route": f"{address}/{s['figmaFrame'].replace(':', '-')}",
                   "pattern": "dashboard", "purpose": s["shows"], "access": "authenticated",
                   "figmaFrame": s["figmaFrame"], "module": s.get("module")}
                  for s in parts[subject]]
    return [ArtifactProposal(section="pages", natural_key=b["route"], body=b) for b in bodies]


def test_a_design_that_fits_one_reply_is_asked_once(tmp_path):
    svc = _svc(tmp_path, screens=SCREENS_PER_CALL)
    assert list(page_set_parts(svc.doc)) == [""]
    assert subjects_for(DAG["page_contracts"], svc.doc) == [""]


def test_five_hundred_screens_are_declared_a_module_at_a_time(tmp_path):
    parts = page_set_parts(_svc(tmp_path).doc)
    drawn = {k: v for k, v in parts.items() if k != FEATURES_PART}
    assert FEATURES_PART not in parts                   # a specification is only its screens
    assert all(0 < len(v) <= SCREENS_PER_CALL for v in drawn.values())
    frames = [s["figmaFrame"] for v in drawn.values() for s in v]
    assert len(frames) == 500 and len(set(frames)) == 500   # every screen, exactly once
    # a module's fifty screens are two parts of its own, never mixed with another's
    assert {"screens:MODULE-001~1", "screens:MODULE-001~2"} <= set(drawn)
    assert {s["module"] for s in drawn["screens:MODULE-001~1"]} == {"MODULE-001"}


def test_under_a_reference_the_rest_of_the_app_is_a_part_of_its_own(tmp_path):
    parts = page_set_parts(_svc(tmp_path, treat="evidence").doc)
    assert FEATURES_PART in parts
    assert not any(s.get("figmaFrame") for s in parts[FEATURES_PART])
    assert any(s.get("entity") == "ENTITY-001" for s in parts[FEATURES_PART])


def test_each_part_is_asked_for_its_own_screens_after_what_every_part_shares(tmp_path):
    svc = _svc(tmp_path, treat="evidence")
    one = build_prompt(svc.doc, "page_contracts", subject="screens:MODULE-001~1")[1]
    two = build_prompt(svc.doc, "page_contracts", subject="screens:MODULE-002~1")[1]
    head, sep, tail = one.partition(CACHE_BREAK)
    assert sep and head == two.partition(CACHE_BREAK)[0]   # the parts share a cached prefix
    assert "Area 0 module's screens (part 1 of 2)" in tail and "`/area-0`" in tail
    assert '"figmaFrame": "0:1"' in tail and '"figmaFrame": "1:1"' not in tail
    rest = build_prompt(svc.doc, "page_contracts", subject=FEATURES_PART)[1].partition(CACHE_BREAK)[2]
    assert "500 DRAWN SCREENS ARE DECLARED BY OTHER CALLS" in rest
    assert "Area 3 (routes under /area-3): 50 screens" in rest and "Screen 493" in rest
    assert "SOME OF THESE SCREENS WERE DRAWN" not in rest   # its slots hold none of them


def test_two_drawn_screens_never_share_a_route(tmp_path):
    svc = _svc(tmp_path, screens=2)
    svc.doc["pages"] = [{"id": "PAGE-001", "name": "Screen 0", "route": "/area-0/home", "figmaFrame": "0:1",
                         "status": "PROPOSED"}]

    def answer(*bodies):
        return AgentResult(task_id="t", agent="page_design", proposals=[
            ArtifactProposal(section="pages", natural_key=b["route"], body=b) for b in bodies])

    with pytest.raises(DrawnScreensShareARoute, match="already the page for the drawn screen"):
        check_drawn_routes(answer({"name": "Screen 1", "route": "/area-0/home", "figmaFrame": "1:1"}), svc.doc)
    with pytest.raises(DrawnScreensShareARoute):
        check_drawn_routes(answer({"name": "A", "route": "/x", "figmaFrame": "1:1"},
                                  {"name": "B", "route": "/X/", "figmaFrame": "2:1"}), svc.doc)
    # the same screen again, and a screen moved off its route, are not clashes
    check_drawn_routes(answer({"name": "Screen 0", "route": "/area-0/home", "figmaFrame": "0:1"}), svc.doc)
    check_drawn_routes(answer({"name": "Screen 0", "route": "/area-0/start", "figmaFrame": "0:1"},
                              {"name": "Screen 1", "route": "/area-0/home", "figmaFrame": "1:1"}), svc.doc)


def test_a_run_declares_every_part_and_each_is_judged_on_its_own_pages(tmp_path):
    svc = _svc(tmp_path, treat="evidence")
    asked: list[str] = []

    def author(spec):
        asked.append(spec.subject)
        return AgentResult(task_id=spec.task_id, agent=spec.agent, confidence=0.9,
                           proposals=_pages_for(svc, spec.subject))

    report = run(svc, author, plan=["page_contracts"])
    assert "page_contracts" in report.completed, report.failed_because
    assert sorted(asked) == sorted(page_set_parts(svc.doc))
    drawn = [p for p in svc.doc["pages"] if p.get("figmaFrame")]
    assert len(drawn) == 500 and len({p["route"] for p in drawn}) == 500
    owner = page_set_part_of(svc.doc)
    page = next(p for p in drawn if p["figmaFrame"] == "10:1")
    assert owner[page["id"]] == "screens:MODULE-001~1"
    rows = _rows(svc.doc, "pages", "screens:MODULE-001~1")
    assert len(rows) == 25 and all(r["module"] == "MODULE-001" for r in rows)


def test_a_resumed_build_declares_only_the_parts_still_missing(tmp_path):
    svc = _svc(tmp_path)
    parts = list(page_set_parts(svc.doc))
    landed = parts[:3]
    rows = [p.body for s in landed for p in _pages_for(svc, s)]
    svc.doc["pages"] = [{**b, "id": f"PAGE-{i + 1:03d}", "status": "PROPOSED"} for i, b in enumerate(rows)]
    node = DAG["page_contracts"]
    assert pending_subjects(node, svc.doc) == parts[3:]
    assert "page_contracts" not in completed_nodes(svc.doc)
    svc.doc["pages"] += [{**p.body, "id": f"PAGE-9{i:02d}", "status": "PROPOSED"}
                         for s in parts[3:] for i, p in enumerate(_pages_for(svc, s))]
    assert pending_subjects(node, svc.doc) == []
    assert "page_contracts" in completed_nodes(svc.doc)
