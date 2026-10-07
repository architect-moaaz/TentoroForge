"""Smith changes any file of the application, directly, and the change lasts.

On UAT 12 of Smith's 121 replies in ten days changed anything: every one-line
fix was a brief to an agent rewriting a whole page or definition (2026-10-07).
`edit_file` and `edit_definition` are exact edits; what happens to each depends
on whose the file is (page, definition, platform, app), and the platform's own
files are patched only on proof.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.smith import file_edit, trials
from services.smith4 import handle
from services.smith4.turn import PATCH_NEEDS_PROOF, REPRODUCE_FIRST, TRY_AFTER
from tests.services._loop_fixtures import _Chooser, _repo, _Writes

ENGINE = "src/lib/workflows/engine.ts"


def _app(tmp_path: Path, rel: str, text: str) -> Path:
    path = tmp_path / "app" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


# --------------------------------------------------------------------------- #
# Whose file is it
# --------------------------------------------------------------------------- #

def test_every_file_has_an_owner():
    doc = {"pages": [{"id": "PAGE-001", "route": "/products", "status": "ACTIVE"}],
           "pageCode": [{"page": "PAGE-001", "view": "export default function V() { return null }", "load": ""}]}
    from services.blueprint.app_sdk import code_page_files
    view = next(p for p in code_page_files(doc, doc["pageCode"][0]) if p.endswith("/view.tsx"))
    assert file_edit.classify(doc, view) == {"kind": "page", "page": "PAGE-001", "key": "view"}
    assert file_edit.classify(doc, "src/lib/workflows/definitions/add-to-cart.json")["kind"] == "definition"
    assert file_edit.classify(doc, "src/db/schema/product.ts")["kind"] == "definition"
    assert file_edit.classify(doc, "src/lib/data-engine.ts")["kind"] == "platform"
    assert file_edit.classify(doc, ENGINE)["kind"] == "platform"
    assert file_edit.classify(doc, "src/sdk/client.tsx")["kind"] == "platform"
    assert file_edit.classify(doc, "src/sdk/workflows.ts")["kind"] == "definition"
    assert file_edit.classify(doc, "src/components/ProductCard.tsx")["kind"] == "app"


# --------------------------------------------------------------------------- #
# The edit
# --------------------------------------------------------------------------- #

def test_an_app_file_is_edited_in_place_and_the_edit_comes_back_after_a_rewrite(tmp_path):
    card = _app(tmp_path, "src/components/ProductCard.tsx", "const label = 'Add to bag';\n")
    out = file_edit.edit_file(str(tmp_path), "src/components/ProductCard.tsx", "'Add to bag'", "'Add to cart'",
                              "the person's word is cart")
    assert out["applied"] and out["kind"] == "app" and "'Add to cart'" in card.read_text()
    (patch,) = file_edit.load_patches(tmp_path)
    assert patch["status"] == "active" and patch["why"] == "the person's word is cart"
    card.write_text("const label = 'Add to bag';\n")                 # something wrote it over
    assert file_edit.reapply(tmp_path) and "'Add to cart'" in card.read_text()
    card.write_text("export const Card = () => null;\n")             # the file moved on
    file_edit.reapply(tmp_path)
    assert file_edit.load_patches(tmp_path)[0]["status"] == "retired"


@pytest.mark.parametrize("find,said", [("'Add to basket'", "not in"), ("x", "appears 3 times")])
def test_an_edit_that_does_not_name_one_place_says_so(tmp_path, find, said):
    _app(tmp_path, "src/components/A.tsx", "x x x 'Add to bag'\n")
    out = file_edit.edit_file(str(tmp_path), "src/components/A.tsx", find, "y")
    assert not out["applied"] and said in out["finding"]


@pytest.mark.parametrize("path", ["app/.env", "app/node_modules/x/index.js", "../elsewhere.txt", "seed.txt"])
def test_credentials_build_output_and_what_is_not_the_app_are_not_edited(tmp_path, path):
    (tmp_path / "seed.txt").write_text("x")
    _app(tmp_path, ".env", "SECRET=x")
    _app(tmp_path, "node_modules/x/index.js", "x")
    assert not file_edit.edit_file(str(tmp_path), path, "x", "y")["applied"]


def test_a_file_written_from_the_definition_is_changed_in_the_definition(tmp_path):
    defn = _app(tmp_path, "src/lib/workflows/definitions/add-to-cart.json", '{"x": 1}')
    out = file_edit.edit_file(str(tmp_path), "src/lib/workflows/definitions/add-to-cart.json", '"x": 1', '"x": 2')
    assert not out["applied"] and "`edit_definition`" in out["finding"] and defn.read_text() == '{"x": 1}'


def test_a_platform_patch_waits_for_proof_and_is_taken_back_without_it(tmp_path):
    engine = _app(tmp_path, ENGINE, "const v = read(path);\n")
    out = file_edit.edit_file(str(tmp_path), ENGINE, "read(path)", "evaluate(path)", "`??` read as one name")
    assert out["applied"] and out["kind"] == "platform" and "kept only if a try after it passes" in out["said"]
    (patch,) = file_edit.load_patches(tmp_path)
    assert patch["status"] == "pending"
    said = file_edit.settle(tmp_path, [patch["id"]], proven=False)
    assert "Took back" in said[0] and engine.read_text() == "const v = read(path);\n"
    assert file_edit.load_patches(tmp_path)[0]["status"] == "reverted"


def test_a_proven_platform_patch_is_filed_and_retires_when_the_platform_has_the_fix(tmp_path, monkeypatch):
    tmp_path = tmp_path / "output" / "app1"                         # one app under its own output root
    engine = _app(tmp_path, ENGINE, "const v = read(path);\n")
    out = file_edit.edit_file(str(tmp_path), ENGINE, "read(path)", "evaluate(path)", "fallbacks")
    file_edit.settle(tmp_path, [out["patch"]], proven=True)
    assert [p["status"] for p in file_edit.open_patches(tmp_path.parent)] == ["active"]
    registry = (tmp_path.parent / file_edit.REGISTRY_DIR / "patches.jsonl").read_text().splitlines()
    assert [json.loads(l)["status"] for l in registry] == ["pending", "active"]
    # A platform refresh wrote the old engine back: the patch is put back.
    monkeypatch.setattr(file_edit, "platform_text", lambda rel: "const v = read(path);\n")
    engine.write_text("const v = read(path);\n")
    file_edit.reapply(tmp_path)
    assert "evaluate(path)" in engine.read_text()
    # The platform folded the fix in: the patch retires and is no longer open.
    monkeypatch.setattr(file_edit, "platform_text", lambda rel: "const v = evaluate(path);\n")
    file_edit.reapply(tmp_path)
    assert file_edit.load_patches(tmp_path)[0]["status"] == "retired"
    assert file_edit.open_patches(tmp_path.parent) == []


def test_a_page_edit_goes_into_the_pages_code_and_must_compile(tmp_path, monkeypatch):
    from services.blueprint.service import BlueprintService
    svc = BlueprintService.create(output_dir=tmp_path, app_id="t", name="Shop", domain="retail")
    svc.doc["pages"] = [{"id": "PAGE-001", "name": "Products", "route": "/products", "purpose": "Browse products",
                         "pattern": "entity_list", "access": "public"}]
    svc.doc["pageCode"] = [{"page": "PAGE-001", "load": "export async function load() { return {} }",
                            "view": "export default function V() { return <p>Add to bag</p> }"}]
    svc.save()
    from services.blueprint.app_sdk import code_page_files
    view = next(p for p in code_page_files(svc.doc, svc.doc["pageCode"][0]) if p.endswith("/view.tsx"))
    _app(tmp_path, view, svc.doc["pageCode"][0]["view"])
    errors: list[list[str]] = [["view.tsx(1,1): error TS2304"]]
    monkeypatch.setattr("services.blueprint.ui_engineer.typecheck", lambda *a, **k: errors.pop(0) if errors else [])
    refused = file_edit.edit_file(str(tmp_path), view, "Add to bag", "Add to cart")
    assert not refused["applied"] and "would not compile" in refused["finding"]
    out = file_edit.edit_file(str(tmp_path), view, "Add to bag", "Add to cart", "their word")
    assert out["applied"] and out["kind"] == "page"
    row = BlueprintService.load(output_dir=tmp_path).doc["pageCode"][0]
    assert "Add to cart" in row["view"] and "Add to cart" in (tmp_path / "app" / view).read_text()


def test_a_definition_edit_is_checked_as_the_build_checks_it(tmp_path, monkeypatch):
    from services.blueprint.service import BlueprintService
    svc = BlueprintService.create(output_dir=tmp_path, app_id="t", name="Shop", domain="retail")
    svc.doc["workflows"] = [{"id": "FLOW-001", "name": "Edit Profile", "trigger": {"kind": "manual"},
                             "inputs": [{"name": "email", "kind": "field", "type": "text", "required": True}], "steps": [
        {"key": "check", "name": "Email not used by another customer", "type": "action",
         "config": {"actionType": "db_query", "table": "customers",
                    "where": {"email": "{{email}}", "id__neq": "$user.id"}}},
        {"key": "done", "name": "Done", "type": "end", "config": {}}]}]
    svc.save()
    synced: list[str] = []
    monkeypatch.setattr("services.smith.sync_app.sync",
                        lambda s, root: synced.append(root) or {"changed": ["src/lib/workflows/definitions/edit-profile.json"],
                                                               "added": [], "removed": [], "database": "in step"})
    bad = file_edit.edit_definition(str(tmp_path), "workflows.FLOW-001", '"Edit Profile"', '"Edit My Profile"')
    assert not bad["applied"] and '{"ne": <value>}' in bad["finding"] and not synced
    good = file_edit.edit_definition(str(tmp_path), "workflows.FLOW-001", '"id__neq": "$user.id"',
                                     '"id": {"ne": "$user.id"}', "email unique among others")
    assert good["applied"] and synced, good
    where = BlueprintService.load(output_dir=tmp_path).doc["workflows"][0]["steps"][0]["config"]["where"]
    assert where == {"email": "{{email}}", "id": {"ne": "$user.id"}}
    assert not file_edit.edit_definition(str(tmp_path), "workflows.FLOW-001", "{", "")["applied"]


# --------------------------------------------------------------------------- #
# The turn holds the edits to proof
# --------------------------------------------------------------------------- #

@pytest.fixture
def tries(monkeypatch):
    answers: list[str] = []
    monkeypatch.setattr(trials, "run", lambda name, args, *, bench, doc:
                        answers.pop(0) if answers else "Add to Cart (FLOW-001) run as Customer: HTTP 200")
    return answers


def _turn(tmp_path, chooser, message="add to cart does not work"):
    return handle(project_id="p1", output_dir=str(tmp_path), message=message, choose=chooser,
                  move=_Writes(tmp_path))


def _edit(path, find="read(path)", replace="evaluate(path)"):
    return {"tool": "edit_file", "args": {"path": path, "find": find, "replace": replace, "why": "fix"}}


_TRY = {"tool": "try_workflow", "args": {"workflow": "FLOW-001", "as": "Customer"}}
_FAILS = "Add to Cart (FLOW-001) run as Customer: HTTP 422\nanswer: not enough stock"


def test_the_first_edit_of_a_turn_that_tried_nothing_is_asked_to_reproduce(tmp_path, tries):
    _repo(tmp_path)
    _app(tmp_path, "src/components/A.tsx", "a\n")
    again = _edit("src/components/A.tsx", "a", "b")
    again["args"]["requested"] = True                              # the change they asked for
    chooser = _Chooser(_edit("src/components/A.tsx", "a", "b"), _edit("src/components/A.tsx", "a", "b"), again, _TRY)
    _turn(tmp_path, chooser, "rename a to b")
    assert chooser.seen[2][-1].said == REPRODUCE_FIRST           # asking twice is not a way past it
    assert chooser.seen[1][-1].said == REPRODUCE_FIRST
    assert (tmp_path / "app/src/components/A.tsx").read_text() == "b\n"


def test_the_platform_is_patched_only_after_a_try_shows_the_fault(tmp_path, tries):
    _repo(tmp_path)
    _app(tmp_path, ENGINE, "const v = read(path);\n")
    chooser = _Chooser(_TRY, _edit(ENGINE))                    # the try passed: no fault to fix
    _turn(tmp_path, chooser)
    assert chooser.seen[2][-1].said == PATCH_NEEDS_PROOF
    assert "read(path)" in (tmp_path / "app" / ENGINE).read_text()


def test_a_change_not_tried_since_is_not_done(tmp_path, tries):
    _repo(tmp_path)
    _app(tmp_path, "src/components/A.tsx", "a\n")
    chooser = _Chooser(_TRY, _edit("src/components/A.tsx", "a", "b"), {"tool": "done", "args": {}})
    _turn(tmp_path, chooser)
    assert chooser.seen[3][-1].said == TRY_AFTER


@pytest.mark.parametrize("after,kept", [("Add to Cart (FLOW-001) run as Customer: HTTP 200", True),
                                        (None, False)])
def test_a_platform_patch_stays_only_when_a_try_after_it_passed(tmp_path, tries, after, kept):
    _repo(tmp_path)
    engine = _app(tmp_path, ENGINE, "const v = read(path);\n")
    tries += [_FAILS] + ([after] if after else [])
    steps = [_TRY, _edit(ENGINE)] + ([_TRY] if after else []) + [{"tool": "done", "args": {}}] * 3
    out = _turn(tmp_path, _Chooser(*steps))
    (patch,) = file_edit.load_patches(tmp_path)
    assert patch["status"] == ("active" if kept else "reverted")
    assert ("evaluate(path)" in engine.read_text()) is kept
    assert ("Kept the platform patch" if kept else "Took back") in out.said


def test_a_page_rewrite_in_a_turn_that_tried_nothing_is_asked_to_reproduce_too(tmp_path, tries, monkeypatch):
    """TCommerce's empty bag went straight to rewriting /cart, then tried."""
    calls = []
    monkeypatch.setattr("services.smith.writes.run", lambda name, args, **k: calls.append(name) or
                        {"applied": True, "said": "Rewrote /cart.", "touched": ["app/src/app/cart/view.tsx"]})
    _repo(tmp_path)
    rewrite = {"tool": "write_page_code", "args": {"route": "/cart", "brief": "show the items"}}
    chooser = _Chooser(rewrite, _TRY, dict(rewrite), _TRY, {"tool": "done", "args": {}})
    _turn(tmp_path, chooser, "the bag is empty after adding")
    assert chooser.seen[1][-1].said == REPRODUCE_FIRST
    assert calls == ["write_page_code"]


def test_a_trial_that_names_nobody_is_the_person_the_screen_is_for():
    """ToroCommerce's fixed minus button was tried as Admin, refused with 422,
    and reported "still does not work" (measured on a copy, 2026-10-07)."""
    from services.smith.trials import default_person
    doc = {"roles": [{"id": "ROLE-001", "name": "Customer"}, {"id": "ROLE-002", "name": "Admin"}],
           "security": {"signupRole": "ROLE-001"},
           "pages": [{"id": "PAGE-003", "route": "/cart", "access": "authenticated"},
                     {"id": "PAGE-006", "route": "/admin/products", "access": "role_restricted", "users": ["ROLE-002"]},
                     {"id": "PAGE-001", "route": "/", "access": "public"}],
           "workflows": [{"id": "FLOW-002", "name": "Update Cart Item Quantity", "launchedFrom": ["PAGE-003"]},
                         {"id": "FLOW-006", "name": "Create Product", "launchedFrom": ["PAGE-006"]}]}
    assert default_person(doc, route="/cart?x=1") == "Customer"
    assert default_person(doc, route="/admin/products") == "Admin"
    assert default_person(doc, route="/") == "Customer"
    assert default_person(doc, flow=doc["workflows"][0]) == "Customer"
    assert default_person(doc, flow=doc["workflows"][1]) == "Admin"
    from services.blueprint.app_check import visits
    by_route = {v["route"]: v["as"] for v in visits(doc) if not v.get("section")}
    assert by_route["/cart"] == "Customer" and by_route["/admin/products"] == "Admin"


def test_a_trial_fills_a_missing_record_with_a_real_one(monkeypatch):
    """TCommerce's empty bag was never reproduced: Smith sent
    `productVariant: "first"`, then `productVariantId: "first"`, and each run
    was refused for the other (measured on a copy, 2026-10-07)."""
    from services.smith.trials import fill_records
    vid = "1d6f02a5-a1dd-4918-9682-e86440f2d964"

    def query(app, sql):
        if "information_schema" in sql:
            return [["id"], ["sku"], ["created_at"]]
        assert 'from "product_variants"' in sql and "order by created_at desc" in sql
        return [[vid, "OCS-S-007"]]

    monkeypatch.setattr("services.blueprint.page_review._query", query)
    doc = {"data": {"entities": [{"id": "ENTITY-004", "name": "ProductVariant", "table": "product_variants",
                                  "labelField": "sku"}]}}
    flow = {"id": "FLOW-001", "inputs": [
        {"entity": "ENTITY-004", "kind": "record", "name": "productVariant", "required": True},
        {"kind": "field", "name": "quantity", "required": True, "type": "integer"},
        {"kind": "field", "name": "productVariantId", "required": True, "type": "string"}]}
    payload = {"productVariant": "first", "quantity": 1}
    said = fill_records(None, doc, flow, payload)
    assert payload == {"productVariant": vid, "quantity": 1, "productVariantId": vid}
    assert said[0] == f"productVariant = ProductVariant OCS-S-007 ({vid})"
    given = {"productVariant": vid, "quantity": 1, "productVariantId": vid}
    assert fill_records(None, doc, flow, dict(given)) == []      # an id given is never replaced


def test_a_workflow_edit_the_app_cannot_be_written_from_is_refused(tmp_path, monkeypatch):
    from services.blueprint.service import BlueprintService
    svc = BlueprintService.create(output_dir=tmp_path, app_id="t", name="Shop", domain="retail")
    svc.doc["workflows"] = [{"id": "FLOW-001", "name": "Ping", "trigger": {"kind": "manual"}, "steps": [
        {"key": "done", "name": "Done", "type": "end", "config": {}}]}]
    svc.save()
    monkeypatch.setattr("services.smith.sync_app.sync", lambda s, root: {"changed": [], "added": [], "removed": [],
                                                                       "database": "in step"})
    def refuse(doc, root):
        raise ValueError("workflow Ping: node id 'trigger' is used twice")
    monkeypatch.setattr("services.blueprint.projection.project_workflows", refuse)
    out = file_edit.edit_definition(str(tmp_path), "workflows.FLOW-001", '"Done"', '"Finished"')
    assert not out["applied"] and "used twice" in out["finding"]
    assert BlueprintService.load(output_dir=tmp_path).doc["workflows"][0]["steps"][0]["name"] == "Done"


def test_a_filled_record_is_one_the_person_can_reach(monkeypatch):
    """The newest cart line was another customer's; the app refused it,
    correctly, and the turn read the refusal as the fault (ToroCommerce copy)."""
    from services.smith.trials import fill_records
    mine = "8426eda8-a93a-4b9a-8299-e7b9128a3888"
    seen: list[str] = []

    def query(app, sql):
        seen.append(sql)
        if "information_schema" in sql:
            return [["id"], ["created_at"]]
        return [[mine]] if mine in sql else [["not-mine"]]

    monkeypatch.setattr("services.blueprint.page_review._query", query)
    doc = {"data": {"entities": [{"id": "ENTITY-005", "name": "CartItem", "table": "cart_items"}]}}
    flow = {"id": "FLOW-002", "inputs": [{"entity": "ENTITY-005", "kind": "record", "name": "cartItem", "required": True}]}
    payload = {"cartItem": "any"}
    fill_records(None, doc, flow, payload, reach=lambda table: [mine])
    assert payload["cartItem"] == mine and f"'{mine}'" in seen[-1]
    none = {"cartItem": "any"}
    said = fill_records(None, doc, flow, none, reach=lambda table: [])
    assert none == {"cartItem": "any"} and "has no CartItem" in said[0]


def test_a_different_control_failing_after_a_fix_is_not_the_same_failure():
    """The minus button was fixed and worked; the plus button answered 422;
    the turn said "failed the same way" (ToroCommerce copy, 2026-10-07)."""
    from services.smith.loop import Observation
    from services.smith4.turn import _failing_note, _still_failing
    before = Observation(tool="open_page", args={"route": "/cart", "as": "Customer"}, status="read",
                         said='/cart as Customer: HTTP 200\ncontrols, each pressed from a fresh load:\n'
                              '  button "Decrease quantity": errors (422)\n  button "Increase quantity": workflow (ran (1))')
    change = Observation(tool="edit_file", args={"path": "src/app/cart/view.tsx"}, status="resolved",
                         said="Changed `src/app/cart/view.tsx`.", touched=["app/src/app/cart/view.tsx"])
    after = Observation(tool="open_page", args={"route": "/cart", "as": "Customer"}, status="read",
                        said='/cart as Customer: HTTP 200\ncontrols, each pressed from a fresh load:\n'
                             '  button "Decrease quantity": workflow (ran (1))\n  button "Increase quantity": errors (422)')
    assert _still_failing([before, change, after]) == []
    note = _failing_note([before, change, after])
    assert "same way" not in note and 'button "Increase quantity"' in note
    still = Observation(tool="open_page", args={"route": "/cart", "as": "Customer"}, status="read",
                        said=before.said)
    assert _still_failing([before, change, still]) and "same way" in _failing_note([before, change, still])
