"""The first screen anyone sees should say what this product is.

Every Blueprint application opened on "Welcome to {app}" above "Welcome back /
Sign in to {app}" — wording built from the application's own name, because
nothing else was ever written. A table of per-archetype greetings exists
(`services.design_dna.AUTH_COPY`) and the Blueprint path never wrote it: the
injector looked for `authCopy` in `design-dna.json` and `project_shell_identity`
emitted only `{_generated, layout, skin}`. Measured on the live host on
2026-11-03: three applications, every one of them exactly those three keys.

Worse, even a written `authCopy` only reached the form. The brand half — the
large words beside it — was built from the name with no override at all.

So: the design agent states the words, the projection carries them to the file
the page reads, and the injector fills all four.
"""
import json
from pathlib import Path

from services.blueprint.projection import (
    AUTH_IDENTITY_PATH, SHELL_IDENTITY_PATH, project_shell_identity,
)
from services.runtime_injector import _substitute_auth_copy

TEMPLATE = (Path(__file__).resolve().parents[2]
            / "templates/app-foundation/src/app/login/page.tsx")


def _doc(**design):
    return {"designSystem": {"colors": {"primary": "#123456"}, **design},
            "navigation": {}, "pages": [{"id": "PAGE-001", "route": "/p1"}]}


def _dna(tmp_path):
    return json.loads((tmp_path / SHELL_IDENTITY_PATH).read_text("utf-8"))


# --- the contract carries it ----------------------------------------------

def test_the_blueprint_can_state_what_the_sign_in_screen_says():
    schema = json.loads((Path(__file__).resolve().parents[2]
                         / "contracts/blueprint.schema.json").read_text("utf-8"))
    props = schema["properties"]["designSystem"]["properties"]["authCopy"]["properties"]
    assert set(props) == {"headline", "subhead", "title", "sub"}


# --- the projection carries it to where the page reads --------------------

def test_the_words_reach_the_file_the_sign_in_page_reads(tmp_path):
    project_shell_identity(_doc(authCopy={
        "headline": "Every refund. One clear trail.",
        "subhead": "Approvals and evidence in one workspace.",
        "title": "Welcome back", "sub": "Log in to {app}."}), tmp_path)
    assert _dna(tmp_path)["authCopy"] == {
        "headline": "Every refund. One clear trail.",
        "subhead": "Approvals and evidence in one workspace.",
        "title": "Welcome back", "sub": "Log in to {app}."}


def test_a_design_that_states_nothing_writes_no_copy_at_all(tmp_path):
    project_shell_identity(_doc(), tmp_path)
    assert "authCopy" not in _dna(tmp_path), (
        "an absent key leaves the fallback standing; an empty one would "
        "override it with nothing")


def test_an_empty_string_is_not_an_override(tmp_path):
    project_shell_identity(_doc(authCopy={"headline": "  ", "title": "Hey, you"}), tmp_path)
    assert _dna(tmp_path)["authCopy"] == {"title": "Hey, you"}


# --- the page is filled with them ------------------------------------------

def _login(tmp_path):
    dest = tmp_path / "src/app/login/page.tsx"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(TEMPLATE.read_text("utf-8"), "utf-8")
    return dest


def test_all_four_reach_the_page_through_the_module(tmp_path):
    _login(tmp_path)
    project_shell_identity(_doc(authCopy={
        "headline": "Every refund. One clear trail.", "subhead": "In one workspace.",
        "title": "Welcome back", "sub": "Log in to {app}."}), tmp_path)

    mod = (tmp_path / AUTH_IDENTITY_PATH).read_text("utf-8")
    for s in ("Every refund. One clear trail.", "In one workspace.",
              "Welcome back", "Log in to {app}."):
        assert s in mod, f"{s!r} did not reach the module the page reads"


def test_no_placeholder_is_left_for_the_build_gate_to_refuse(tmp_path):
    """`assembly.refuse_unfilled_scaffold` refuses any `__NAME__` that ships,
    and it is right to: a placeholder that survives renders to the user. The
    sign-in screen therefore carries none — the module is the source, and a
    real sentence is the floor under it."""
    _login(tmp_path)
    from services.blueprint import assembly
    assert not {t for t in assembly.scaffold_tokens() if t.startswith("__AUTH_")}
    page = (tmp_path / "src/app/login/page.tsx").read_text("utf-8")
    assert "__AUTH_" not in page


def test_without_a_design_the_old_wording_still_stands(tmp_path):
    _login(tmp_path)
    project_shell_identity(_doc(), tmp_path)

    mod = (tmp_path / AUTH_IDENTITY_PATH).read_text("utf-8")
    assert '"headline": ""' in mod and '"title": ""' in mod, "nothing stated, nothing claimed"
    page = (tmp_path / "src/app/login/page.tsx").read_text("utf-8")
    assert "`Welcome to ${APP_NAME}`" in page and '"Welcome back"' in page


# --- and the agent is asked for them ---------------------------------------

def test_the_design_agent_is_told_to_write_them():
    from services.blueprint.executors import NODE_TASKS
    prompt = NODE_TASKS["design_system"]
    assert "authCopy" in prompt
    assert "{app}" in prompt
    assert "headline" in prompt and "subhead" in prompt


# --- a design changed later still reaches the first screen ----------------
#
# The real defect behind the wording: the page held `__AUTH_LAYOUT__` and
# `__AUTH_HEADLINE__` literals that the injector replaced ONCE. After that the
# placeholder was gone, so a later design had nothing to write to. Mark 8's
# design-dna.json says `centered-minimal` and its login page still says
# `split-editorial` — measured on the live host, 2026-11-03.



def _module(tmp_path):
    return (tmp_path / AUTH_IDENTITY_PATH).read_text("utf-8")


def test_the_sign_in_screen_is_a_projected_module_not_a_one_shot_edit(tmp_path):
    project_shell_identity(_doc(shell={"chrome": "dock", "auth": "brand-wash"}), tmp_path)
    assert '"layout": "brand-wash"' in _module(tmp_path)

    # The design changes, as it does on turn fifty.
    project_shell_identity(_doc(shell={"chrome": "topbar", "auth": "centered-minimal"},
                                authCopy={"headline": "Second thoughts."}), tmp_path)
    again = _module(tmp_path)
    assert '"layout": "centered-minimal"' in again, (
        "a re-projection must move the sign-in screen; this is the Mark 8 bug")
    assert '"headline": "Second thoughts."' in again


def test_the_name_is_resolved_where_it_is_known(tmp_path):
    doc = _doc(authCopy={"sub": "Log in to {app}."})
    doc["application"] = {"name": "Criterion CARES"}
    project_shell_identity(doc, tmp_path)
    assert '"sub": "Log in to Criterion CARES."' in _module(tmp_path), (
        "the projection knows the name, so the page holds a finished sentence "
        "and the acronym survives (the injector would title-case it)")


def test_the_page_reads_the_module_and_falls_back_to_a_real_sentence():
    login = (Path(__file__).resolve().parents[2]
             / "templates/app-foundation/src/app/login/page.tsx").read_text("utf-8")
    assert 'from "@/contracts/auth-identity"' in login
    assert "AUTH_IDENTITY.headline" in login and "AUTH_IDENTITY.layout" in login
    assert "const said = (stated: string, fallback: string)" in login
    assert "{HEADLINE}" in login and "{SUBHEAD}" in login
    assert "__AUTH_" not in login, "a placeholder can ship unfilled; a sentence cannot"


def test_the_scaffold_ships_a_copy_so_a_tree_without_the_projection_compiles():
    from services.blueprint.assembly import SCAFFOLD_DEFAULTS
    assert "src/contracts/auth-identity.ts" in SCAFFOLD_DEFAULTS
    stub = (Path(__file__).resolve().parents[2]
            / "templates/app-foundation/src/contracts/auth-identity.ts").read_text("utf-8")
    assert "export const AUTH_IDENTITY" in stub and "export type AuthIdentity" in stub
