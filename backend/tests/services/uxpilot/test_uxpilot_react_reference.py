"""UX Pilot as the designer of the React pages.

The page writer used to decide every page itself; UX Pilot's schema path ended
when pages became React. Now the design is drawn first, from the page's brief,
and the writer ADAPTS it — keeping what the designer decided, and holding the
result to the same compiler and wiring checks as any page."""
from __future__ import annotations

import dataclasses
import json
import re

import pytest

from services.blueprint import executors as ex
from services.blueprint import page_look, ui_engineer
from services.blueprint.service import BlueprintService
from services.blueprint.ui_engineer import compose_page, reference_block, reference_digest
from services.uxpilot import generate as g

GOOD_VIEW = '"use client";\nexport default function View() { return <div className="p-6" />; }\n'
GOOD_LOAD = 'import type { PageContext } from "@/sdk/server";\nexport async function load(ctx: PageContext) { return {}; }\n'

HTML = """<!doctype html><html><head><title>x</title><style>.a{color:red}</style>
<script src="https://cdn.tailwindcss.com"></script></head><body class="bg-white">
<!-- a comment --><aside>Sidebar</aside>
<main><h1>Tasks</h1><svg width="20"><path d="M0 0 L10 10 L20 0 L30 30 L40 0"/></svg>
<img src="data:image/png;base64,AAAAAAAAAAAAAAAAAAAAAAAAAAAA"/>
<table><tr><th>Title</th><th>Status</th></tr><tr><td>Follow up with client</td><td>Todo</td></tr></table>
</main><script>window.x = 1</script></body></html>"""


def _doc():
    return {
        "application": {"id": "t", "name": "Desk", "description": "Cases.", "uiDesigner": "uxpilot"},
        "data": {"entities": [{"id": "ENTITY-001", "name": "Case", "fields": [
            {"name": "title", "type": "string", "required": True},
            {"name": "status", "type": "enum", "enumValues": ["Todo", "In Progress", "Done"]}]}]},
        "pages": [{"id": "PAGE-001", "name": "All Cases", "route": "/cases", "purpose": "Every case.",
                   "pattern": "entity_list", "data": {"primaryEntity": "ENTITY-001"},
                   "navigatesTo": ["PAGE-002"]},
                  {"id": "PAGE-002", "name": "Case Detail", "route": "/cases/[id]", "purpose": "One.",
                   "pattern": "record_workspace", "data": {"primaryEntity": "ENTITY-001"}}],
        "workflows": [{"id": "FLOW-001", "name": "Create Case", "launchedFrom": ["PAGE-001"],
                       "inputs": [{"name": "title", "kind": "field", "type": "text"},
                                  {"name": "status", "kind": "field", "type": "enum"}]}],
        "composition": {"vision": "Calm.", "conventions": []},
    }


REF = {"html": HTML, "previewUrl": "https://ux/p.png", "designId": "dsg_1"}


def _plain():
    """The same application, nothing launched from its pages: what the compiler's
    wiring checks would otherwise (rightly) demand of every view."""
    doc = _doc()
    doc["workflows"][0]["launchedFrom"] = []
    return doc


# --------------------------------------------------------------------------- #
# What the writer is shown
# --------------------------------------------------------------------------- #

def test_the_digest_keeps_the_page_and_drops_what_decides_nothing():
    out = reference_digest(HTML)
    assert "<h1>Tasks</h1>" in out and "<th>Title</th>" in out
    for gone in ("<script", "<style", "a comment", "cdn.tailwindcss", "M0 0 L10", "base64"):
        assert gone not in out, gone
    assert "<svg/>" in out, "a picture is a place, not its path data"


def test_a_long_design_is_cut_on_a_tag_boundary():
    out = reference_digest("<body>" + "<p>row</p>" * 5000 + "</body>", limit=1000)
    assert len(out) < 1200 and out.rstrip().endswith("-->")
    assert out.split(" <!--")[0].endswith(">"), "never in the middle of a tag"


def test_the_block_says_the_design_is_the_decision_and_its_literals_are_not_data():
    block = reference_block(REF)
    assert "Preview: https://ux/p.png" in block
    assert "THE DESIGN IS THE DECISION" in block
    assert "invented" in block and "load.ts" in block
    assert "href(pages.x)" in block and "workflow" in block


# --------------------------------------------------------------------------- #
# compose_page
# --------------------------------------------------------------------------- #

class _Client:
    max_tokens = 64000

    def __init__(self, replies=None):
        self.replies = list(replies or [{"rationale": "", "load": GOOD_LOAD, "view": GOOD_VIEW}])
        self.calls, self.schemas = [], []

    def __call__(self, *, system, user, schema):
        self.calls.append(user)
        self.schemas.append(schema)
        if "sections" in (schema.get("properties") or {}):
            return json.dumps({"state": "x", "sections": ["a"], "behaviours": ["b"]})
        return json.dumps(self.replies.pop(0) if len(self.replies) > 1 else self.replies[0])

    @property
    def writes(self):
        return [u for u, sc in zip(self.calls, self.schemas) if "load" in (sc.get("properties") or {})]

    @property
    def plans(self):
        return [u for u in self.calls if u.startswith("Decide how to build")]


def test_a_designed_page_is_not_planned_the_design_is_the_plan(monkeypatch, tmp_path):
    monkeypatch.setattr(ui_engineer, "typecheck", lambda *a, **k: [])
    client = _Client()
    compose_page(_plain(), _plain()["pages"][0], tmp_path, client, reference=REF)
    assert client.plans == []
    assert len(client.writes) == 1
    assert "A design for this page" in client.writes[0] and "Follow up with client" in client.writes[0]
    assert "Your plan for it" not in client.writes[0]


def test_without_a_design_the_page_is_planned_as_it_always_was(monkeypatch, tmp_path):
    monkeypatch.setattr(ui_engineer, "typecheck", lambda *a, **k: [])
    client = _Client()
    compose_page(_plain(), _plain()["pages"][0], tmp_path, client)
    assert len(client.plans) == 1
    assert "A design for this page" not in client.writes[0]


def test_a_designed_page_is_written_plainly_not_at_full_effort(monkeypatch, tmp_path):
    """The design decided; the budget is for the page, as after a plan."""
    from services.blueprint.ui_engineer import WRITE_EFFORT, WRITE_MAX_TOKENS

    @dataclasses.dataclass
    class _Model:
        effort: str = "high"
        max_tokens: int = 64000
        asked: list = dataclasses.field(default_factory=list)

        def __call__(self, *, system, user, schema):
            self.asked.append((self.effort, self.max_tokens))
            return json.dumps({"rationale": "", "load": GOOD_LOAD, "view": GOOD_VIEW})

    monkeypatch.setattr(ui_engineer, "typecheck", lambda *a, **k: [])
    model = _Model()
    compose_page(_plain(), _plain()["pages"][0], tmp_path, model, reference=REF)
    assert model.asked == [(WRITE_EFFORT, WRITE_MAX_TOKENS)]


def test_the_house_style_rules_do_not_pull_a_designed_page_back(monkeypatch, tmp_path):
    monkeypatch.setattr(ui_engineer, "typecheck", lambda *a, **k: [])
    monkeypatch.setattr(ui_engineer, "_design_findings", lambda *a, **k: ["use the accent once"])
    seeded = _Client()
    compose_page(_plain(), _plain()["pages"][0], tmp_path, seeded, reference=REF)
    assert len(seeded.writes) == 1, "accepted on the first round"

    plain = _Client()
    compose_page(_plain(), _plain()["pages"][0], tmp_path, plain)
    assert len(plain.writes) == 3, "the same findings do hold a page the model decided itself"


def test_a_repair_round_does_not_resend_the_design(monkeypatch, tmp_path):
    """The code exists by then; what is wanted is a fix."""
    answers = iter([["use client is missing"], []])
    monkeypatch.setattr(ui_engineer, "typecheck", lambda *a, **k: next(answers))
    client = _Client()
    compose_page(_plain(), _plain()["pages"][0], tmp_path, client, reference=REF)
    assert len(client.writes) == 2
    assert "A design for this page" in client.writes[0]
    assert "A design for this page" not in client.writes[1]


def test_a_change_to_an_existing_page_ignores_a_design(monkeypatch, tmp_path):
    monkeypatch.setattr(ui_engineer, "typecheck", lambda *a, **k: [])
    client = _Client([{"rationale": "", "load": "", "view": "", "edits": []}])
    compose_page(_plain(), _plain()["pages"][0], tmp_path, client, reference=REF,
                 current={"load": GOOD_LOAD, "view": GOOD_VIEW}, brief="make the title bigger")
    assert all("A design for this page" not in u for u in client.writes)


@pytest.mark.parametrize("seeded", [True, False])
def test_the_reviewer_sends_a_designed_page_back_only_for_something_broken(monkeypatch, tmp_path, seeded):
    monkeypatch.setattr(ui_engineer, "typecheck", lambda *a, **k: [])
    verdict = {"verdict": "revise", "score": 4, "broken": [],
               "issues": [{"problem": "a little dull", "severity": "low"}]}
    monkeypatch.setattr(page_look, "look_at", lambda *a, **k: (dict(verdict), (None, 0.0)))
    client = _Client()
    compose_page(_plain(), _plain()["pages"][0], tmp_path, client, critic=object(),
                 reference=REF if seeded else None)
    assert len(client.writes) == (1 if seeded else 2)


def test_a_designed_page_that_is_broken_still_goes_back(monkeypatch, tmp_path):
    monkeypatch.setattr(ui_engineer, "typecheck", lambda *a, **k: [])
    verdicts = iter([{"verdict": "revise", "score": 2, "broken": ["the table is empty"], "issues": []},
                     {"verdict": "pass", "score": 8, "broken": [], "issues": []}])
    monkeypatch.setattr(page_look, "look_at", lambda *a, **k: (next(verdicts), (None, 0.0)))
    client = _Client()
    compose_page(_plain(), _plain()["pages"][0], tmp_path, client, critic=object(), reference=REF)
    assert len(client.writes) == 2


# --------------------------------------------------------------------------- #
# reference_for: who asks, who is spared, what is said
# --------------------------------------------------------------------------- #

class _Gateway:
    """Plays UX Pilot's design agent: one job draws one screen for every
    `=== Screen "Name"` the prompt asks for, titled with that name."""
    may_generate = True

    def __init__(self, fail=None):
        self.calls, self.fail, self.prompts, self._titles = [], fail, [], []

    async def call(self, tool, **kw):
        if tool == "start_design_agent":
            self.calls.append(tool)      # the one call that spends credits
            self.prompts.append(kw["prompt"])
            self._titles = re.findall(r'=== Screen "([^"]+)"', kw["prompt"])
        if self.fail:
            raise self.fail
        if tool == "start_design_agent":
            body = {"agentJobId": "job_1", "status": "queued"}
        elif tool == "get_agent_job":
            body = {"status": "completed", "screens": [
                {"designId": f"dsg_{i}", "title": f"App - {t}", "previewUrl": "https://ux/p.png"}
                for i, t in enumerate(self._titles, 1)]}
        else:
            body = {"design": {"id": kw.get("design"), "html": HTML}}
        return [{"type": "text", "text": json.dumps(body)}]


def test_one_run_draws_every_page_of_the_application(tmp_path):
    doc = _doc()
    doc["designSystem"] = {"visualPersonality": "Calm and uncluttered", "colors": {"primary": "#1f6f5c"}}
    gw = _Gateway()
    first, _ = g.reference_for(doc, doc["pages"][0], tmp_path, gateway=gw)
    second, _ = g.reference_for(doc, doc["pages"][1], tmp_path, gateway=gw)
    assert gw.calls == ["start_design_agent"], "one credit-spending run for the whole application"
    assert first["designId"] == "dsg_1" and second["designId"] == "dsg_2"
    for page in doc["pages"]:
        assert f'=== Screen "{page["name"]}"' in gw.prompts[0]
    assert gw.prompts[0].count("Design language") == 1, "the shared style is said once, not per page"


def test_parallel_page_writers_share_one_run(tmp_path):
    import concurrent.futures

    doc = _doc()
    gw = _Gateway()
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda p: g.reference_for(doc, p, tmp_path, gateway=gw)[0], doc["pages"] * 2))
    assert all(r and r["html"] for r in results)
    assert gw.calls == ["start_design_agent"]


def test_a_page_the_forge_designs_is_not_asked_about(tmp_path):
    doc = _doc()
    doc["application"]["uiDesigner"] = "forge"
    assert g.reference_for(doc, doc["pages"][0], tmp_path, gateway=_Gateway()) == (None, "")


def test_an_unanswered_application_means_the_forge(tmp_path, monkeypatch):
    monkeypatch.delenv("FORGE_UI_DESIGNER", raising=False)
    doc = _doc()
    del doc["application"]["uiDesigner"]
    assert g.reference_for(doc, doc["pages"][0], tmp_path, gateway=_Gateway()) == (None, "")


def test_the_platform_default_decides_only_where_nobody_chose(tmp_path, monkeypatch):
    """`FORGE_UI_DESIGNER` turns UX Pilot on for applications that have no answer
    of their own; an answer on the application or the page, `forge` included,
    always outranks it."""
    monkeypatch.setenv("FORGE_UI_DESIGNER", "uxpilot")
    doc = _doc()
    del doc["application"]["uiDesigner"]
    assert g.designer_for(doc, doc["pages"][0]) == "uxpilot"
    ref, _ = g.reference_for(doc, doc["pages"][0], tmp_path, gateway=_Gateway())
    assert ref and ref["designId"] == "dsg_1"

    doc["application"]["uiDesigner"] = "forge"
    assert g.designer_for(doc, doc["pages"][0]) == "forge", "the application's own answer wins"
    doc["pages"][0]["designedBy"] = "uxpilot"
    assert g.designer_for(doc, doc["pages"][0]) == "uxpilot", "and the page's own answer wins over that"


@pytest.mark.parametrize("value", ["", "figma", "UXPILOTT", "  "])
def test_a_default_that_names_no_designer_is_ignored(monkeypatch, value):
    monkeypatch.setenv("FORGE_UI_DESIGNER", value)
    doc = _doc()
    del doc["application"]["uiDesigner"]
    assert g.designer_for(doc, doc["pages"][0]) == "forge"


def test_a_sign_in_page_is_never_drawn_by_the_designer(tmp_path):
    doc = _doc()
    doc["pages"][0]["pattern"] = "auth"
    gw = _Gateway()
    assert g.reference_for(doc, doc["pages"][0], tmp_path, gateway=gw) == (None, "")
    assert gw.calls == []


def test_the_designer_chosen_per_page_beats_the_applications(tmp_path):
    doc = _doc()
    doc["pages"][0]["designedBy"] = "forge"
    gw = _Gateway()
    assert g.reference_for(doc, doc["pages"][0], tmp_path, gateway=gw)[0] is None
    ref, said = g.reference_for(doc, doc["pages"][1], tmp_path, gateway=gw)
    assert ref and ref["designId"] == "dsg_1" and "Adapting UX Pilot design dsg_1" in said


def test_the_design_comes_back_with_its_markup_and_preview(tmp_path):
    doc = _doc()
    ref, said = g.reference_for(doc, doc["pages"][0], tmp_path, gateway=_Gateway())
    assert ref["html"] == HTML and ref["previewUrl"] == "https://ux/p.png" and ref["reused"] is False
    assert "/cases" in said


def test_an_unchanged_brief_spends_nothing_the_second_time(tmp_path):
    doc = _doc()
    gw = _Gateway()
    g.reference_for(doc, doc["pages"][0], tmp_path, gateway=gw)
    ref, said = g.reference_for(doc, doc["pages"][0], tmp_path, gateway=gw)
    assert gw.calls == ["start_design_agent"], "one credit-spending call, however many builds"
    assert ref["reused"] is True and "reused" in said


def test_a_changed_brief_is_drawn_again(tmp_path):
    doc = _doc()
    gw = _Gateway()
    g.reference_for(doc, doc["pages"][0], tmp_path, gateway=gw)
    doc["pages"][0]["purpose"] = "Every case, newest first."
    g.reference_for(doc, doc["pages"][0], tmp_path, gateway=gw)
    assert gw.calls == ["start_design_agent", "start_design_agent"]


def test_no_key_means_the_page_is_written_without_a_design_and_says_so(tmp_path, monkeypatch):
    monkeypatch.delenv("UXPILOT_API_KEY", raising=False)
    doc = _doc()
    ref, said = g.reference_for(doc, doc["pages"][0], tmp_path)
    assert ref is None
    assert "no API key" in said and "UXPILOT_API_KEY" in said and "/cases" in said


def test_a_failed_generation_never_costs_the_page(tmp_path):
    from services.uxpilot.gateway import UxPilotGatewayError

    doc = _doc()
    ref, said = g.reference_for(doc, doc["pages"][0], tmp_path,
                                gateway=_Gateway(fail=UxPilotGatewayError("auth", "bad key")))
    assert ref is None and "could not design" in said and "without a design" in said


def test_a_surprise_from_the_gateway_is_a_sentence_not_a_crash(tmp_path):
    ref, said = g.reference_for(_doc(), _doc()["pages"][0], tmp_path, gateway=_Gateway(fail=RuntimeError("boom")))
    assert ref is None and "RuntimeError" in said


# --------------------------------------------------------------------------- #
# The brief UX Pilot is given
# --------------------------------------------------------------------------- #

def test_the_prompt_names_the_values_the_links_and_what_an_action_asks_for():
    doc = _doc()
    prompt = g.prompt_for(doc, doc["pages"][0])
    assert '"Todo", "In Progress", "Done"' in prompt and "badge" in prompt
    assert 'open other pages, labelled exactly: "Case Detail"' in prompt
    assert 'The "Create Case" action opens a short form asking for: "Title", "Status"' in prompt


def test_the_prompt_stays_deterministic_so_the_ledger_means_unchanged():
    doc = _doc()
    assert g.prompt_for(doc, doc["pages"][0]) == g.prompt_for(doc, doc["pages"][0])


# --------------------------------------------------------------------------- #
# The executor: where the design is fetched
# --------------------------------------------------------------------------- #

def _svc(tmp_path):
    svc = BlueprintService.create(output_dir=tmp_path, app_id="a", name="Desk", domain="Ops")
    svc.doc.update({k: v for k, v in _doc().items() if k in ("data", "pages", "workflows")})
    svc.doc["application"]["uiDesigner"] = "uxpilot"
    return svc


def _spec(**kw):
    return ex.TaskSpec(task_id="T-page_code-PAGE-001", node="page_code", agent="ui_engineer",
                       subject="PAGE-001", **kw)


def _capture(monkeypatch):
    seen: dict = {}

    def compose(doc, page, root, client, **kw):
        seen.update(kw)
        return {"page": page["id"], "view": GOOD_VIEW, "load": GOOD_LOAD}, []

    monkeypatch.setattr(ui_engineer, "compose_page", compose)
    return seen


def test_the_executor_hands_the_writer_the_pages_design(tmp_path, monkeypatch):
    seen = _capture(monkeypatch)
    asked = []

    def reference_for(doc, page, output_dir, **kw):
        asked.append(page["id"])
        return REF, "Adapting UX Pilot design dsg_1 for /cases."

    monkeypatch.setattr(g, "reference_for", reference_for)
    result = ex.make_executor(_svc(tmp_path), object())(_spec())
    assert asked == ["PAGE-001"]
    assert seen["reference"] == REF
    assert result.proposals[0].section == "pageCode"


def test_a_page_without_a_design_is_written_without_one(tmp_path, monkeypatch):
    seen = _capture(monkeypatch)
    monkeypatch.setattr(g, "reference_for", lambda *a, **k: (None, "UX Pilot has no key"))
    ex.make_executor(_svc(tmp_path), object())(_spec())
    assert seen["reference"] is None


def test_a_change_to_a_page_never_redraws_it(tmp_path, monkeypatch):
    seen = _capture(monkeypatch)
    asked = []
    monkeypatch.setattr(g, "reference_for", lambda *a, **k: asked.append(1) or (REF, ""))
    ex.make_executor(_svc(tmp_path), object())(_spec(brief="make the heading bigger"))
    assert asked == [] and seen["reference"] is None


# --------------------------------------------------------------------------- #
# Found by reading the real prompts of a built application
# --------------------------------------------------------------------------- #

def _todo():
    doc = _doc()
    doc["workflows"] = [{"id": "FLOW-001", "name": "Add Task", "launchedFrom": ["PAGE-001"], "inputs": []}]
    doc["pages"][0]["actions"] = ["Add task"]
    doc["widgets"] = [
        {"id": "WIDGET-001", "page": "PAGE-001", "kind": "metric", "label": "To do", "order": 1,
         "dataSource": {"op": "query", "entity": "ENTITY-001", "filter": {"status": "Todo"},
                        "measures": [{"aggregation": "count", "key": "n", "label": "To do"}]}},
        {"id": "WIDGET-002", "page": "PAGE-001", "kind": "chart", "label": "By status", "order": 2,
         "dataSource": {"op": "query", "entity": "ENTITY-001",
                        "measures": [{"aggregation": "count", "key": "n", "label": "n"}],
                        "dimensions": [{"field": "status"}]}},
    ]
    return doc


def test_a_metric_the_analytics_agent_wrote_reaches_the_design():
    """Widgets are `op: query` now; the prompt only knew `op: aggregate`, so every
    metric tile of every current application was left out of what UX Pilot drew."""
    doc = _todo()
    prompt = g.prompt_for(doc, doc["pages"][0])
    assert 'Metric tiles, each with its label and one number: "To do".' in prompt
    assert "By status" not in prompt, "a chart grouped by something is not one number"


def test_a_workflows_name_and_the_pages_word_for_it_are_one_button():
    doc = _todo()
    prompt = g.prompt_for(doc, doc["pages"][0])
    assert 'Buttons, labelled exactly: "Add Task".' in prompt
    assert "Add task" not in prompt.split("Buttons, labelled exactly:")[1].split("\n")[0]


def test_a_record_page_is_drawn_as_one_record_not_a_table_of_them():
    doc = _doc()
    record = g.prompt_for(doc, doc["pages"][1])          # /cases/[id], record_workspace
    assert "One Case shown in full, as a record rather than a list" in record
    assert "A table of" not in record
    listing = g.prompt_for(doc, doc["pages"][0])         # /cases, entity_list
    assert "A table of Cases with exactly these column headers" in listing
