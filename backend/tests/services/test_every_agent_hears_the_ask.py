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
