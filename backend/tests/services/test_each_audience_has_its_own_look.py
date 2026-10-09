"""Each kind of person gets the look their kind of product needs (2026-10-08).

ToroCommerce's shoppers and its staff are two products to two kinds of
people — a shop window browsed on a phone and a console worked in all day —
and the app had one frame and one page rhythm for both. When the design said
nothing the code filled the gap from words in the personality ("child",
"family", "consumer" made a tinted rail; "back-office" a dark one), and
`application.domain` was "unknown" in every Blueprint, so no agent choosing
the look was told what the product is.

Now the product frame states its field and its kind (`product.domain`,
`product.category`), the director gives every audience — each role, and the
visitors when there are public pages — exactly one look from those and from
how its people use it (`composition.looks`), and the app draws the signed-in
person's look, paints the visitors' header in theirs, and writes each page in
the rhythm of the people it is for.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from services.blueprint import looks as lk

ROOT = Path(__file__).resolve().parents[2]

RHYTHM_SHOP = {"header": "band", "lead": "gradient-band", "lists": "cards", "figures": "inline", "sections": "open"}
RHYTHM_DESK = {"header": "compact", "lead": "outlined-panel", "lists": "table", "figures": "strip", "sections": "dense"}

DOC = {
    "application": {"name": "Shop", "domain": "unknown"},
    "product": {"domain": "clothing retail", "category": "a shop people browse and buy from; a console its staff run",
                "personas": [{"name": "Customer", "description": "buys on a phone", "goals": ["Buy clothes"]},
                             {"name": "Admin", "description": "runs the catalogue all day"}]},
    "designSystem": {"colors": {"primary": "#123456"},
                     "shell": {"chrome": "standard-rail", "auth": "brand-wash", "tone": "light"}},
    "roles": [{"id": "ROLE-001", "name": "Customer"}, {"id": "ROLE-002", "name": "Admin"}],
    "pages": [
        {"id": "PAGE-001", "name": "Home", "route": "/", "access": "public"},
        {"id": "PAGE-002", "name": "My orders", "route": "/orders", "users": ["ROLE-001"]},
        {"id": "PAGE-003", "name": "Products", "route": "/admin/products", "users": ["ROLE-002"],
         "access": "role_restricted"},
    ],
    "composition": {"vision": "v", "conventions": [], "looks": [
        {"audience": ["public", "ROLE-001"], "experience": "browsed on a phone", "chrome": "topbar",
         "tone": "tinted", "rhythm": RHYTHM_SHOP, "why": "a shop window"},
        {"audience": ["ROLE-002"], "experience": "worked in all day at a desk", "chrome": "wide-rail",
         "tone": "dark", "rhythm": RHYTHM_DESK, "why": "a console"},
    ]},
    "navigation": {},
}


def _doc():
    return copy.deepcopy(DOC)


# --- the product says what it is -------------------------------------------------------

def test_the_contract_carries_the_field_the_kind_and_a_look_per_audience():
    schema = json.loads((ROOT / "contracts" / "blueprint.schema.json").read_text())
    product = schema["properties"]["product"]["properties"]
    assert {"domain", "category"} <= set(product)
    look = schema["properties"]["composition"]["properties"]["looks"]["items"]
    assert set(look["required"]) == {"audience", "experience", "chrome", "tone", "rhythm", "why"}
    assert "CRM | HRMS" not in json.dumps(schema["properties"]["application"]), "no list of fields to pick from"


def test_a_product_frame_that_does_not_say_what_it_is_is_asked_again():
    from services.blueprint.agent_contract import InvalidProductFrame, check_product_frame
    bare = SimpleNamespace(agent="product_analysis",
                           proposals=[SimpleNamespace(section="product", body={"objectives": ["x"]})])
    with pytest.raises(InvalidProductFrame, match="`domain`.*`category`"):
        check_product_frame(bare, {})
    said = SimpleNamespace(agent="product_analysis", proposals=[SimpleNamespace(
        section="product", body={"domain": "clothing retail", "category": "a shop"})])
    check_product_frame(said, {})
    other = SimpleNamespace(agent="requirement", proposals=bare.proposals)
    check_product_frame(other, {})  # only the product frame's author is held to it
    more = SimpleNamespace(agent="product_analysis", proposals=[SimpleNamespace(
        section="product", body={"capabilities": [{"name": "Search"}]})])
    check_product_frame(more, {"product": {"domain": "clothing retail", "category": "a shop"}})  # said before
    from services.blueprint.executors import NODE_TASKS
    assert "SAY WHAT THE PRODUCT IS" in NODE_TASKS["application_model"]


# --- every audience, exactly one look ------------------------------------------------

def test_the_audiences_are_the_roles_and_the_visitors_when_there_are_public_pages():
    assert lk.audiences(_doc()) == ["ROLE-001", "ROLE-002", "public"]
    doc = _doc()
    doc["pages"] = doc["pages"][1:]
    assert lk.audiences(doc) == ["ROLE-001", "ROLE-002"]


@pytest.mark.parametrize("mend,needle", [
    (lambda d: d["composition"]["looks"].pop(), "Admin (`ROLE-002`) has no look"),
    (lambda d: d["composition"]["looks"][0]["audience"].remove("public"), "the visitors (`public`) has no look"),
    (lambda d: d["composition"]["looks"][1]["audience"].append("ROLE-001"), "Customer (`ROLE-001`) has 2 looks"),
    (lambda d: d["composition"]["looks"][1]["audience"].append("ROLE-404"), "ROLE-404, who is not one"),
    (lambda d: d["composition"]["looks"][1].update(tone="neon"), "names no `tone`"),
    (lambda d: d["composition"]["looks"][1]["rhythm"].pop("lists"), "no page rhythm for `lists`"),
])
def test_a_look_missing_or_doubled_is_named(mend, needle):
    doc = _doc()
    assert lk.look_findings(doc, doc["composition"]["looks"]) == []
    mend(doc)
    found = lk.look_findings(doc, doc["composition"]["looks"])
    assert any(needle in f for f in found), found


def test_the_director_is_refused_naming_whose_look_is_missing():
    from services.blueprint.agent_contract import InvalidLooks, check_looks
    doc = _doc()
    body = {"vision": "v", "conventions": [], "looks": doc["composition"]["looks"][:1]}
    result = SimpleNamespace(agent="ui_director", proposals=[SimpleNamespace(section="composition", body=body)])
    with pytest.raises(InvalidLooks, match="Admin"):
        check_looks(result, doc)
    body["looks"] = doc["composition"]["looks"]
    check_looks(result, doc)


# --- the director decides from the field, the kind and the people ---------------------

def test_the_director_is_told_what_the_product_is_and_who_needs_a_look():
    from services.blueprint.ui_engineer import DIRECTION_SCHEMA, direction_prompts
    _, user = direction_prompts(_doc())
    assert "Its field: clothing retail" in user and "What kind of product it is: a shop people browse" in user
    assert "- `ROLE-001` — Customer; buys on a phone; Buy clothes. Their screens (1): My orders" in user
    assert "- `public` — visitors who are not signed in. Their screens (1): Home" in user
    assert "ONE LOOK FOR EACH AUDIENCE" in user
    assert "consumer product wants" not in user, "no kind of product mapped to an answer"
    assert "looks" in DIRECTION_SCHEMA["required"]
    _, again = direction_prompts(_doc(), brief="give the staff a dark wide rail", feedback="Admin has no look")
    assert "THIS IS A CHANGE" in again and "give the staff a dark wide rail" in again
    assert "YOUR LAST ANSWER WAS REFUSED — mend it: Admin has no look" in again


def test_the_directors_looks_are_kept_as_it_wrote_them():
    from services.blueprint.ui_engineer import compose_direction
    reply = json.dumps({"vision": "v", "conventions": [{"topic": "t", "rule": "r"}],
                        "looks": DOC["composition"]["looks"]})
    seen = {}

    def client(**kw):
        seen.update(kw)
        return reply
    body, _ = compose_direction(_doc(), client, feedback="Admin has no look")
    assert body["looks"] == DOC["composition"]["looks"]
    assert "Admin has no look" in seen["user"]
    src = (ROOT / "services/blueprint/executors.py").read_text()
    assert 'feedback=spec.feedback or ""' in src and 'brief=getattr(spec, "brief", "") or ""' in src


# --- the app draws each person's look ---------------------------------------------------

def test_each_role_gets_its_frame_and_the_visitors_their_header(tmp_path):
    from services.blueprint.projection import (RAIL_PAINT, SHELL_IDENTITY_PATH, project_public_nav,
                                               project_shell_identity, public_nav)
    project_shell_identity(_doc(), tmp_path)
    dna = json.loads((tmp_path / SHELL_IDENTITY_PATH).read_text())
    assert dna["layout"]["chrome"] == "standard-rail" and dna["layout"]["auth"] == "brand-wash"
    assert dna["looks"]["Admin"] == {"chrome": "wide-rail", "tone": "dark", **RAIL_PAINT["dark"]}
    assert dna["looks"]["Customer"]["chrome"] == "topbar" and dna["looks"]["Customer"]["bg"] == RAIL_PAINT["tinted"]["bg"]
    assert "public" not in dna["looks"] and "visitors" not in dna["looks"]
    assert public_nav(_doc())["paint"] == {"tone": "tinted", **RAIL_PAINT["tinted"]}
    doc = _doc()
    doc["composition"]["looks"][0]["audience"] = ["ROLE-001"]
    assert "paint" not in public_nav(doc), "no look for visitors: the header stays the card it was"
    project_public_nav(_doc(), tmp_path)
    assert "paint?: PublicPaint" in (tmp_path / "src/contracts/public-nav.ts").read_text()


def test_the_layout_and_the_public_header_read_the_look():
    layout = (ROOT / "templates/app-foundation/src/app/(dashboard)/layout.tsx").read_text()
    assert "const look = identity.looks?.[role];" in layout
    assert 'identity.frame = look.chrome === "topbar" ? "topbar" : "sidebar"' in layout
    frame = (ROOT / "templates/app-foundation/src/components/PublicPageFrame.tsx").read_text()
    assert "(PUBLIC_NAV as { paint?:" in frame and "style={paint ? { background: paint.bg, color: paint.text }" in frame
    scaffold = (ROOT / "templates/app-foundation/src/contracts/public-nav.ts").read_text()
    assert "paint?: PublicPaint" in scaffold


# --- each page is written in its people's rhythm ----------------------------------------

def test_a_page_keeps_to_the_rhythm_of_the_people_it_is_for():
    from services.blueprint.ui_engineer import _page_brief, derive_rhythm, system_prompt
    doc = _doc()
    home, orders, products = doc["pages"]
    assert derive_rhythm(doc, home) == RHYTHM_SHOP and derive_rhythm(doc, orders) == RHYTHM_SHOP
    assert derive_rhythm(doc, products) == RHYTHM_DESK
    prompt = system_prompt(doc)
    assert "For visitors, Customer — browsed on a phone:" in prompt and "For Admin — worked in all day" in prompt
    assert prompt == system_prompt(doc), "the cached prefix is the same for every page"
    assert _page_brief(doc, products)["look"] == {"for": "Admin", "rhythm": RHYTHM_DESK}
    one = _doc()
    one["composition"]["looks"] = one["composition"]["looks"][1:]
    assert "look" not in _page_brief(one, one["pages"][2]), "one look: nothing to choose between"


def test_a_role_with_no_look_keeps_the_applications_frame():
    doc = _doc()
    doc["composition"]["looks"] = doc["composition"]["looks"][1:]
    customer = lk.look_for(doc, "ROLE-001")
    assert (customer["chrome"], customer["tone"]) == ("standard-rail", "light"), "the design's own shell"
    from services.blueprint.ui_engineer import RHYTHM_DEFAULT
    assert customer["rhythm"] == RHYTHM_DEFAULT


# --- Smith sees each look and changes one ----------------------------------------------

def test_smith_reads_each_look_and_can_change_one():
    from services.smith.engine_blueprint_adapter import to_smith_fields
    from services.smith.writes import SECTION_NODE, SECTION_WORDS
    from services.smith_blueprint import Blueprint
    from services.smith_blueprint_context import blueprint_to_context
    assert SECTION_NODE["composition"] == "ui_direction" and SECTION_WORDS["composition"]
    bp = Blueprint(project_id="p")
    for k, v in to_smith_fields(_doc()).items():
        setattr(bp, k, v)
    text = blueprint_to_context(bp)
    assert "## How each kind of person sees it" in text
    assert "The product: clothing retail — a shop people browse" in text
    assert "Admin — worked in all day at a desk: wide-rail, dark; header compact" in text
