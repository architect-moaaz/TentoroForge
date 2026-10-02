"""Every agent Smith briefs hears what was asked, and what it touches.

Three things were missing (2026-10-02): the agents got Smith's one-line
reading of the ask, never the person's words; the page writer never saw the
requirements its page answers to ("dish names must be unique" on the dish
form); the data model agent never saw which screens read which fields, and
renamed `image` to `photo` in passing.
"""
from __future__ import annotations

from types import SimpleNamespace

from services.blueprint.page_usage import entity_usage, page_requirements, usage_brief
from services.smith import asked

DOC = {
    "modules": [{"id": "MODULE-001", "requirements": ["REQ-001"]}],
    "requirements": [
        {"id": "REQ-001", "description": "Admin can add a dish with a name and price."},
        {"id": "REQ-004", "description": "Admin can edit a dish."},
        {"id": "REQ-011", "description": "Dish names must be unique."},
        {"id": "REQ-099", "description": "Customers can pay online."},
    ],
    "data": {"entities": [{"id": "ENTITY-002", "name": "FoodItem", "fields": [
        {"name": "id"}, {"name": "name"}, {"name": "price"}, {"name": "image"}, {"name": "spiceLevel"}]}]},
    "workflows": [{"id": "FLOW-006", "launchedFrom": ["PAGE-008"], "requirements": ["REQ-004"]}],
    "businessRules": [{"id": "RULE-009", "entity": "ENTITY-002", "appliesTo": ["ENTITY-002"], "requirements": ["REQ-011"]}],
    "pages": [
        {"id": "PAGE-008", "route": "/admin/food-items/[id]", "module": "MODULE-001",
         "data": {"primaryEntity": "ENTITY-002"}},
        {"id": "PAGE-010", "route": "/login"},
    ],
    "pageCode": [{"page": "PAGE-008", "load": "const d = await get(\"FoodItem\", id)",
                  "view": "<input value={d.name} /><img src={fileUrl(d.image)} /> {d.price}"}],
}


def test_a_page_answers_to_its_module_its_processes_and_the_rules_on_its_records():
    got = page_requirements(DOC, DOC["pages"][0])
    assert [r["id"] for r in got] == ["REQ-001", "REQ-004", "REQ-011"]
    assert got[2]["statement"] == "Dish names must be unique."
    assert page_requirements(DOC, DOC["pages"][1]) == []


def test_the_page_writer_is_given_them():
    from services.blueprint.ui_engineer import _page_brief
    brief = _page_brief(DOC, DOC["pages"][0])
    assert {"id": "REQ-011", "statement": "Dish names must be unique."} in brief["requirements"]
    assert "requirements" not in _page_brief(DOC, DOC["pages"][1])


def test_which_screens_read_which_fields():
    assert entity_usage(DOC) == {"FoodItem": [{"route": "/admin/food-items/[id]", "fields": ["name", "price", "image"]}]}
    said = usage_brief(DOC)
    assert "FoodItem on /admin/food-items/[id]: name, price, image" in said and "keep every field" in said


def test_the_persons_words_go_beside_smiths_reading():
    token = asked.ASKED.set("prices need paise, two decimals please")
    try:
        out = asked.with_their_words("Change FoodItem.price to a decimal.")
        assert out.startswith("Change FoodItem.price to a decimal.")
        assert "\"prices need paise, two decimals please\"" in out
        assert asked.with_their_words("prices need paise, two decimals please") == \
            "prices need paise, two decimals please", "not said twice"
    finally:
        asked.ASKED.reset(token)
    assert asked.with_their_words("x") == "x", "no turn, nothing added"


def test_a_section_agent_hears_the_ask_and_the_data_agent_the_screens(monkeypatch):
    import services.smith.section_change as sc
    briefs = []

    def run(spec):
        briefs.append((spec.node, spec.brief))
        return SimpleNamespace(proposals=[])
    monkeypatch.setattr(sc, "executor_for", lambda svc, executor, reasoning: run)
    svc = SimpleNamespace(doc=DOC)
    token = asked.ASKED.set("make dish names unique")
    try:
        for node in ("entity_fields", "workflow_steps"):
            try:
                sc.rerun(svc, node, brief="Set FoodItem.name unique.", request="x", interpretation="x")
            except sc.SectionChangeError:
                pass
    finally:
        asked.ASKED.reset(token)
    data_brief = next(b for n, b in briefs if n == "entity_fields")
    flow_brief = next(b for n, b in briefs if n == "workflow_steps")
    assert "\"make dish names unique\"" in data_brief and "\"make dish names unique\"" in flow_brief
    assert "FoodItem on /admin/food-items/[id]" in data_brief
    assert "Screens that already use" not in flow_brief, "the workflow agent sees the pages itself"


def test_a_page_rewrite_hears_the_ask(monkeypatch):
    from services.smith import writes
    seen = []
    monkeypatch.setattr(writes, "write_page_code", lambda out, route, brief, **k: seen.append(brief) or {})
    token = asked.ASKED.set("show prices with the rupee sign")
    try:
        writes.run("write_page_code", {"route": "/", "brief": "Format prices as INR."}, output_dir="/tmp/x")
    finally:
        asked.ASKED.reset(token)
    assert "Format prices as INR." in seen[0] and "\"show prices with the rupee sign\"" in seen[0]


def test_a_change_to_a_record_type_is_a_patch_onto_it():
    """Asked for two-decimal prices, the data agent returned FoodItem without
    `photoEmbedding` and without the id's `unique` — both were applied as
    removals (2026-10-02). Left out is kept; restated is changed."""
    from services.blueprint.agent_contract import ArtifactProposal
    from services.smith.section_change import _as_patches
    svc = SimpleNamespace(doc={"data": {"entities": [{"id": "ENTITY-002", "name": "FoodItem", "fields": [
        {"name": "id", "type": "uuid", "unique": True}, {"name": "price", "type": "decimal"},
        {"name": "photoEmbedding", "type": "vector"}]}]}})
    prop = ArtifactProposal("data.entities", "fooditem", {"id": "ENTITY-002", "name": "FoodItem", "fields": [
        {"name": "id", "type": "uuid"}, {"name": "price", "type": "decimal(10,2)"}, {"name": "spiceLevel", "type": "string"}]})
    new = ArtifactProposal("data.entities", "review", {"name": "Review", "fields": [{"name": "stars"}]})
    _as_patches(svc, [prop, new])
    assert prop.body["fields"] == [
        {"name": "id", "type": "uuid", "unique": True},
        {"name": "price", "type": "decimal(10,2)"},
        {"name": "photoEmbedding", "type": "vector"},
        {"name": "spiceLevel", "type": "string"}]
    assert new.body["fields"] == [{"name": "stars"}], "a new record type is taken as proposed"


def test_a_plans_steps_carry_the_ask_it_was_made_from(tmp_path):
    """"Prices need paise … show prices as ₹" became a plan; each step ran with
    only its own words, and the page writers never saw the person's
    (2026-10-02)."""
    from services.smith import plan as plan_mod
    from services.smith4.handle import handle as run_handle
    from tests.services._loop_fixtures import _Chooser, _repo
    _repo(tmp_path)
    plan_mod.remember(tmp_path, ["make price two decimals", "show prices as ₹ everywhere"],
                      agreed=False, asked="Prices need paise, and show ₹ on every screen.")
    assert plan_mod.asked_of(tmp_path) == "Prices need paise, and show ₹ on every screen."
    plan_mod.take_next(tmp_path)
    assert plan_mod.asked_of(tmp_path) == "Prices need paise, and show ₹ on every screen.", "kept while steps remain"

    heard = []

    def choose(ask, page, seen, history):
        heard.append(asked.ASKED.get())
        return {"tool": "done", "args": {}, "why": ""}
    run_handle(project_id="p", output_dir=str(tmp_path), message=plan_mod.FIRST_LABEL, choose=choose)
    assert heard and "Prices need paise, and show ₹ on every screen." in heard[0]
    assert "show prices as ₹ everywhere" in heard[0]

    heard.clear()
    run_handle(project_id="p", output_dir=str(tmp_path), message="rename the app", choose=choose)
    assert heard and "Prices need paise" not in heard[0], "a new ask does not inherit an old plan's words"


def test_a_review_rewrite_hears_the_ask(monkeypatch):
    from services.smith import writes
    got = {}
    monkeypatch.setattr("services.blueprint.service.BlueprintService.load",
                        classmethod(lambda cls, output_dir: SimpleNamespace(doc={"pages": []})))
    monkeypatch.setattr("services.blueprint.orchestrator.review_coded_pages",
                        lambda svc, root, only=None, asked="": got.setdefault("asked", asked) and {"pages": {}})
    token = asked.ASKED.set("show prices as ₹ with two decimals")
    try:
        writes.run("verify_pages", {}, output_dir="/tmp/nowhere")
    finally:
        asked.ASKED.reset(token)
    assert "\"show prices as ₹ with two decimals\"" in got["asked"]


def test_smith_is_told_a_recorded_requirement_changes_no_screen():
    from services.smith.loop import _PROMPT
    assert "A REQUIREMENT RECORDED IS NOT A CHANGE MADE" in _PROMPT and "`rewrite_pages`" in _PROMPT


def test_a_restated_field_keeps_its_nested_settings_and_nothing_empty_wipes_one():
    from services.smith.section_change import _onto
    have = {"name": "photoEmbedding", "type": "vector", "embedding": {"of": "image", "model": "clip"}}
    assert _onto(have, {"name": "photoEmbedding", "embedding": {"of": ""}, "required": True}) == \
        {"name": "photoEmbedding", "type": "vector", "embedding": {"of": "image", "model": "clip"}, "required": True}
    assert _onto({"type": "decimal"}, {"type": "decimal(10,2)"}) == {"type": "decimal(10,2)"}


def test_a_parameterised_type_is_its_kind_everywhere():
    """`decimal(10,2)` became a text column, a string in the SDK and a text box
    on the dish form (2026-10-02)."""
    from services.blueprint.app_sdk import _numeric, ts_type
    from services.blueprint.projection import base_type, emit_entity_module
    price = {"name": "price", "type": "decimal(10,2)"}
    assert base_type("Decimal(10, 2)") == "decimal" and base_type("varchar(255)") == "varchar"
    assert ts_type(price) == "number" and _numeric(price)
    module = emit_entity_module({"id": "ENTITY-1", "name": "FoodItem", "table": "food_items",
                                 "fields": [{"name": "id", "type": "uuid", "primaryKey": True}, price]}, {})
    assert 'price: numeric("price")' in module


def test_a_plain_yes_to_a_deletion_is_heard_and_a_qualified_one_is_not():
    """"Yes, delete it" brought the same question back four times (F&B,
    2026-10-02)."""
    from services.smith.confirm import is_yes
    for said in ("Yes, delete it", "yes remove it", "go ahead and delete it", "yes", "Go ahead"):
        assert is_yes(said), said
    assert is_yes("yes please remove the about page", "/about")
    for said in ("Yes, but rename it first", "no, leave it", "don't delete it", "the page", "wait"):
        assert not is_yes(said), said


def test_a_removal_rewrites_the_coded_screens_that_use_what_went(monkeypatch):
    """The Delete Category process was removed and Category Details kept its
    button over `workflows.deleteCategory` — a page that no longer compiles
    (F&B live test, 2026-10-02). The same holds for a field and a link."""
    from services.smith import compose
    svc = SimpleNamespace(doc={
        "pages": [{"id": "PAGE-006", "route": "/admin/categories/[id]", "data": {"primaryEntity": "ENTITY-001"}},
                  {"id": "PAGE-001", "route": "/", "data": {"primaryEntity": "ENTITY-002"}}],
        "pageCode": [{"page": "PAGE-006", "view": "<WorkflowButton workflow={workflows.deleteCategory} /> {c.description}"},
                     {"page": "PAGE-001", "view": "{item.description} <Link href={href(pages.about)} />"}]})
    assert [p["id"] for p in compose.pages_using(svc, r"\bworkflows\.deleteCategory\b")] == ["PAGE-006"]
    assert [p["id"] for p in compose.pages_using(svc, r"\.description\b", entity_id="ENTITY-002")] == ["PAGE-001"]
    assert [p["id"] for p in compose.pages_using(svc, r"\bpages\.about\b")] == ["PAGE-001"]

    asked_for = []

    def recode(s, route, *, app_root, request, reasoning=None, **k):
        asked_for.append((route, request))
        if route == "/":
            raise compose.ComposeError("did not compile")
        return {}
    monkeypatch.setattr(compose, "recode_page", recode)
    done, notes = compose.recode_pages_using(svc, "/app", svc.doc["pages"], "take away workflows.deleteCategory")
    assert done == ["/admin/categories/[id]"] and "did not compile" in notes[0]
    assert all(r == "take away workflows.deleteCategory" for _route, r in asked_for)
    assert compose.recode_pages_using(svc, None, svc.doc["pages"], "x") == ([], []), "no app, nothing to rewrite"


def test_a_record_type_is_renamed_in_place(monkeypatch):
    """"Call reviews 'feedback'" added a second record type beside Review
    (F&B live test, 2026-10-02): same id, fields and table now."""
    from services.smith import compose, entity_change

    class Svc:
        output_dir = "/tmp/x"

        def __init__(self):
            self.doc = {"data": {"entities": [{"id": "ENTITY-005", "name": "Review", "table": "reviews",
                                               "fields": [{"name": "stars"}]}]},
                        "pages": [{"id": "PAGE-020", "route": "/admin/reviews"}],
                        "pageCode": [{"page": "PAGE-020", "view": "import type { Review } from '@/sdk'; list(\"Review\")"}]}
            self.commits = []

        def snapshot(self): return json.loads(json.dumps(self.doc))
        def validate(self): pass
        def commit(self, **k): self.commits.append(k)

    import json
    svc = Svc()
    rewritten = []
    monkeypatch.setattr(compose, "recode_page", lambda s, route, **k: rewritten.append((route, k["request"])) or {})
    monkeypatch.setattr(entity_change, "_project_data", lambda s, root: [])
    monkeypatch.setattr("services.blueprint.ui_engineer.ensure_sdk", lambda doc, root: None)
    out = entity_change.rename_entity(svc, "reviews", "feedback", app_root="/tmp/app")
    e = svc.doc["data"]["entities"]
    assert len(e) == 1 and e[0] == {"id": "ENTITY-005", "name": "Feedback", "table": "reviews", "fields": [{"name": "stars"}]}
    assert out["old"] == "Review" and out["pages"] == ["/admin/reviews"] and "SDK's Feedback" in rewritten[0][1]
    assert entity_change.rename_entity(svc, "Feedback", "feedback")["already"]


def test_a_screen_only_access_change_reaches_the_screens(monkeypatch):
    """"Only admins should be able to open the order details page": the
    roles step rightly changed nothing, that was taken as a refusal, and the
    screen stayed open to customers (F&B live test, 2026-10-02)."""
    import json as _json
    from services.smith import access_change as ac

    def empty_rerun(svc, node, **k):
        raise ac.SectionChangeError(f"refused 2 times and nothing has been changed. The last reason was: {k['empty']}")
    monkeypatch.setattr(ac, "rerun", empty_rerun)
    monkeypatch.setattr(ac, "record_requirement", lambda svc, text, owner: {"id": "REQ-20"})
    svc = SimpleNamespace(doc={
        "roles": [{"id": "ROLE-001", "name": "Admin"}, {"id": "ROLE-002", "name": "Customer"}],
        "pages": [{"id": "PAGE-011", "route": "/admin/orders/[id]", "access": "authenticated", "users": ["ROLE-001"]}]},
        upsert=lambda section, body, natural_key: svc.doc["pages"][0].update(body), save=lambda: None)
    answer = SimpleNamespace(text=_json.dumps({"pages": [{"page": "PAGE-011", "access": "role_restricted", "roles": ["Admin"]}]}))
    out = ac.change_access(svc, "Only admins should be able to open the order details page.",
                           client=lambda **k: answer)
    assert out["pages_changed"] == ["/admin/orders/[id]"]
    assert svc.doc["pages"][0]["access"] == "role_restricted" and svc.doc["pages"][0]["users"] == ["ROLE-001"]


def test_a_plan_step_hears_what_the_steps_before_it_did(tmp_path):
    from services.smith import plan as plan_mod
    from services.smith4.handle import _all_steps
    from services.smith4.outcome import Outcome
    plan_mod.remember(tmp_path, ["add the spice level", "show it on the admin forms"], agreed=True)
    seen = []

    def run(step):
        seen.append(step)
        return Outcome(status="resolved", said="Added spiceLevel and put it on the Add and Edit forms.")
    _all_steps(str(tmp_path), run)
    assert seen[0] == "add the spice level"
    assert seen[1].startswith("show it on the admin forms") and "put it on the Add and Edit forms" in seen[1]


def test_a_turn_out_of_steps_says_what_its_tries_showed(tmp_path, monkeypatch):
    from services.smith4 import turn as turn_mod
    from tests.services._loop_fixtures import _repo
    from services.smith4.handle import handle
    _repo(tmp_path)
    monkeypatch.setattr(turn_mod.trials, "run", lambda tool, args, **k: f"{tool} {args.get('route', '')}: HTTP 200\\nall fine")
    steps = iter([{"tool": "open_page", "args": {"route": f"/r{i}"}, "why": ""} for i in range(4)])

    def choose(ask, page, seen, history):
        return next(steps, {"tool": "read_section", "args": {"name": "pages"}, "why": ""})
    out = handle(project_id="p", output_dir=str(tmp_path), message="images do not show", choose=choose, max_steps=3)
    assert "What I tried, and what it showed:" in out.said and "open_page /r0: HTTP 200" in out.said


def test_a_yes_to_a_waiting_confirmation_is_not_a_yes_to_the_plan(tmp_path):
    """Asked "shall I go ahead?" inside an agreed plan, the yes ran the plan's
    NEXT step and the removal it answered never happened (F&B live test,
    2026-10-02)."""
    from services.smith import confirm, pending_ask
    from services.smith import plan as plan_mod
    from services.smith4.handle import handle
    from tests.services._loop_fixtures import _repo
    _repo(tmp_path)
    plan_mod.remember(tmp_path, ["retire REQ-011", "update the toggle process"], agreed=True)
    pending_ask.remember(tmp_path, "remove the spice level field")
    confirm.remember(tmp_path, confirm.fingerprint("remove_field", "FoodItem.spiceLevel"))
    heard = []

    def choose(ask, page, seen, history):
        heard.append(ask)
        return {"tool": "done", "args": {}, "why": ""}
    handle(project_id="p", output_dir=str(tmp_path), message="Yes, go ahead.", choose=choose)
    assert heard and "remove the spice level field" in heard[0] and "retire REQ-011" not in heard[0]
    assert plan_mod.peek(tmp_path) == ["retire REQ-011", "update the toggle process"], "the plan waits"


def test_an_unreachable_model_is_said_not_nothing_needed(tmp_path):
    """The account's credit ran out mid-test and "add a spice level" was
    answered "Nothing needed doing" (2026-10-02)."""
    from services.smith4.handle import handle
    from tests.services._loop_fixtures import _repo
    _repo(tmp_path)
    out = handle(project_id="p", output_dir=str(tmp_path), message="add a spice level",
                 choose=lambda *a: {"tool": "done", "args": {}, "unreachable": True, "why": "x"})
    assert "could not reach my reasoning service" in out.said and "Nothing needed doing" not in out.said
    assert "nothing was changed" in out.said


def test_the_loop_marks_an_unreachable_provider():
    from services.smith.loop import next_step

    def down(prompt):
        raise RuntimeError("Your credit balance is too low")
    step = next_step("add a spice level", "", [], provider=down)
    assert step["tool"] == "done" and step.get("unreachable") is True
