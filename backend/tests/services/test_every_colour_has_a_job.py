"""Every colour has a job, the design's type reaches the page, and a page is
written against both.

Tool Share (036farqu) chose a forest green and a terracotta that were close to
the reference it was measured against and shipped a white-and-green app: the
terracotta was drawn three times in eighteen pages, headings fell back to the
browser's Times because `typography.fontFamily` was a name the projector did
not read, card text was the scaffold's navy, and rows said "Tool #a1b2…".
"""
from __future__ import annotations

import json
import pathlib

from services.blueprint.executors import NODE_TASKS
from services.blueprint.projection import (
    _font_roles, _font_stack, _token_contract, project_design_tokens, resolved_palette,
)
from services.blueprint.ui_engineer import DESIGN_PRINCIPLES, SDK_GUIDE, _design_findings, _look
from services.blueprint.verification import PALETTE_ROLES, check_palette_roles

_ROOT = pathlib.Path(__file__).resolve().parents[3]
_TEMPLATE = _ROOT / "backend" / "templates" / "app-foundation"

FOREST = {
    "background": "#F7F4EE", "surface": "#FFFFFF", "textPrimary": "#1F2A24", "textSecondary": "#5B6560",
    "primary": "#24382F", "accent": "#B4623F", "accentSubtle": "#F6E3D9", "inverse": "#24382F",
    "border": "#E4E0D8",
}


def _doc(colors=None, typography=None, **design):
    return {"designSystem": {"colors": colors if colors is not None else dict(FOREST),
                             "typography": typography or {}, **design}}


# --------------------------------------------------------------------- colour

def test_the_contract_has_a_tint_and_a_dark_surface():
    tokens = {t["token"]: t for t in _token_contract()["colorTokens"]}
    assert tokens["accent-subtle"]["role"] == ["accentSubtle"]
    assert tokens["inverse"]["role"][0] == "inverse"
    assert tokens["inverse-foreground"]["contrastOf"] == "inverse"


def test_secondary_is_quiet_not_a_second_accent():
    pal = resolved_palette(_doc())
    assert pal["secondary"] != pal["accent"]


def test_computed_text_is_the_palettes_own_ink_and_paper():
    pal = resolved_palette(_doc())
    ink, paper = pal["foreground"], pal["background"]
    assert pal["card-foreground"] == ink            # not the scaffold's navy
    assert pal["inverse-foreground"] == paper        # the page's paper on the dark card
    assert pal["primary-foreground"] == paper


def test_a_palette_with_no_ink_still_gets_readable_text():
    pal = resolved_palette({"designSystem": {"colors": {"accent": "#F59E0B"}}})
    assert pal["accent-foreground"] == "222 84% 5%"


def test_an_authored_palette_names_every_job():
    colors = {k: v for k, v in FOREST.items() if k not in ("accentSubtle", "inverse")}
    missing = {f.artifact_id for f in check_palette_roles(_doc(colors))}
    assert missing == {"colors.accentSubtle", "colors.inverse"}
    assert check_palette_roles(_doc()) == []


def test_a_palette_read_off_figma_is_not_held_to_the_jobs():
    assert check_palette_roles(_doc({"primary": "#123456"}, derivedFromFigma=True)) == []


def test_the_new_pairs_are_contrast_checked():
    from services.blueprint.verification import _contrast_ratio, check_palette_contrast
    assert check_palette_contrast(_doc()) == []
    for card in ("#24382F", "#8FA89A", "#3A2A1F"):      # whatever the dark card, its text reads
        pal = resolved_palette(_doc(dict(FOREST, inverse=card)))
        assert _contrast_ratio(pal["inverse-foreground"], pal["inverse"]) >= 4.5, card


def test_the_chip_text_is_the_accent_deepened_until_it_reads():
    from services.blueprint.verification import _contrast_ratio
    pal = resolved_palette(_doc())
    fg, bg = pal["accent-subtle-foreground"], pal["accent-subtle"]
    assert _contrast_ratio(fg, bg) >= 4.5
    assert fg.split()[0] == pal["accent"].split()[0]          # same hue, deeper
    assert fg != pal["accent"]


def test_the_projected_chip_text_matches_what_is_checked(tmp_path):
    project_design_tokens(_doc(), tmp_path)
    css = (tmp_path / "src/app/tokens.css").read_text()
    assert f"--accent-subtle-foreground: {resolved_palette(_doc())['accent-subtle-foreground']};" in css


def test_the_designer_is_told_each_job():
    task = NODE_TASKS["design_system"]
    for role in PALETTE_ROLES:
        assert f"`{role}`" in task
    assert "fontFamilyHeading" in task and "fontFamilyBase" in task


# ----------------------------------------------------------------------- type

def test_what_the_designer_calls_a_font_is_read():
    roles = _font_roles({"fontFamily": "Inter, system-ui, sans-serif", "headingFontFamily": "Fraunces"})
    assert roles["fontFamilyBase"] == "Inter, system-ui, sans-serif"
    assert roles["fontFamilyHeading"] == "Fraunces"


def test_a_stack_is_quoted_as_css_reads_it():
    assert _font_stack('"Libre Caslon Text", Georgia, serif') == '"Libre Caslon Text", Georgia, serif'
    assert _font_stack("DM Sans, system-ui") == '"DM Sans", system-ui'


def test_both_faces_are_loaded_and_applied(tmp_path):
    project_design_tokens(_doc(typography={"fontFamily": "Inter, system-ui, sans-serif",
                                           "fontFamilyHeading": '"Fraunces", Georgia, serif'}), tmp_path)
    css = (tmp_path / "src/app/tokens.css").read_text()
    assert "family=Inter:" in css and "family=Fraunces:" in css
    assert "system-ui:" not in css and "Georgia:" not in css      # system faces are not requested
    assert '--font-heading: "Fraunces", Georgia, serif;' in css or "--font-heading: Fraunces, Georgia, serif;" in css
    assert "--font-body: Inter, system-ui, sans-serif;" in css
    assert "h1, h2, h3, .font-heading" in css


def test_tailwind_exposes_the_jobs_and_the_faces():
    src = (_TEMPLATE / "tailwind.config.ts").read_text()
    for needle in ("var(--accent-subtle", "var(--accent-subtle-foreground", "var(--inverse",
                   "var(--inverse-foreground", "heading: [\"var(--font-heading)\"", "sans: [\"var(--font-body)\""):
        assert needle in src, needle


def test_the_accent_is_a_button_and_a_submit():
    assert 'accent:\n          "bg-accent' in (_TEMPLATE / "src/components/ui/button.tsx").read_text()
    client = (_TEMPLATE / "src/sdk/client.tsx").read_text()
    assert 'submitVariant?: "primary" | "accent"' in client
    assert '"primary" | "accent" | "secondary"' in client


def test_neutral_hovers_are_not_drawn_in_the_accent():
    for f in ("button.tsx", "badge.tsx", "select.tsx", "dialog.tsx"):
        src = (_TEMPLATE / "src/components/ui" / f).read_text()
        assert "hover:bg-accent " not in src and "focus:bg-accent" not in src and "open]:bg-accent" not in src, f


# ----------------------------------------------------------------- the pages

def _page(pid="PAGE-1", **kw):
    return {"id": pid, "route": "/rentals", "pattern": "entity_list", **kw}


def _launching(pid="PAGE-1"):
    return {"workflows": [{"id": "FLOW-1", "launchedFrom": [pid]}]}


def test_an_id_shown_to_a_reader_is_sent_back():
    for view in ('<p>Tool #{shortId(r.toolId)}</p>', '<p>Tool #{tool.id.slice(0, 8)}</p>',
                 'const ref = rental.id.slice(0, 8);', '<span>{r.toolId}</span>',
                 '<p>{`Owner #${ownerId.slice(0, 6)}`}</p>'):
        assert any("shows an id" in f for f in _design_findings({}, _page(), view)), view


def test_an_id_that_is_not_text_is_fine():
    view = ('<Link key={r.id} href={href(pages.rental, { id: r.id })}>{tools[r.toolId]?.name}</Link>'
            '<WorkflowButton workflow={workflows.x} input={{ rentalId: r.id }} />')
    assert _design_findings({}, _page(), view) == []


def test_a_browser_face_for_a_title_is_sent_back():
    assert any("font-heading" in f for f in _design_findings({}, _page(), '<h1 className="font-serif">x</h1>'))


def test_a_page_that_acts_draws_its_action_in_the_accent():
    plain = '<WorkflowForm workflow={workflows.x} fields={{}} />'
    assert any("accent" in f for f in _design_findings(_launching(), _page(), plain))
    for ok in ('<WorkflowForm workflow={workflows.x} fields={{}} submitVariant="accent" />',
               '<Button variant="accent">Start return</Button>',
               '<span className="bg-accent-subtle text-accent-subtle-foreground">Active</span>'):
        assert _design_findings(_launching(), _page(), ok) == [], ok
    # a hover in the accent is not the accent
    assert _design_findings(_launching(), _page(), '<a className="hover:bg-accent">x</a>')
    # a page that launches nothing is not asked for one
    assert _design_findings({}, _page(), plain) == []


def test_the_engineer_is_told_the_jobs_and_shown_the_palette():
    for needle in ('variant="accent"', "bg-inverse", "recordsById", "NAMES, NEVER IDS",
                   "LEAD WITH WHAT MATTERS NOW", "SAY WHAT HAPPENS NEXT", "font-heading"):
        assert needle in DESIGN_PRINCIPLES + SDK_GUIDE, needle
    look = _look(_doc(typography={"fontFamilyBase": "Inter", "fontFamilyHeading": "Fraunces"}))
    assert "bg-accent" in look and "#B4623F" in look and "Fraunces" in look


def test_the_sdk_and_the_editor_samples_can_look_up_related_records():
    assert "export async function recordsById" in (_TEMPLATE / "src/sdk/server.ts").read_text()
    assert "export async function recordsById" in (_ROOT / "backend/static/jit-samples.mjs").read_text()


def test_the_contract_file_is_still_json():
    json.loads((_ROOT / "packages/library/src/theme/token-contract.json").read_text())


def test_a_style_finding_asks_again_but_never_costs_the_page(monkeypatch, tmp_path):
    import json as _json

    from services.blueprint import ui_engineer as ue

    monkeypatch.setattr(ue, "typecheck", lambda *a, **k: [])
    monkeypatch.setattr(ue, "system_prompt", lambda doc: "s")
    monkeypatch.setattr(ue, "user_prompt", lambda *a, **k: "u")
    calls, client_view = [], []

    def client(*, system, user, schema):
        calls.append(user)
        return _json.dumps({"rationale": "r", "load": "export async function load() { return {}; }",
                            "view": client_view[0]})

    from services.blueprint.app_sdk import workflow_keys
    doc = {"workflows": [{"id": "FLOW-1", "name": "Request to borrow", "launchedFrom": ["PAGE-1"]}]}
    key = workflow_keys(doc)["FLOW-1"]
    view = ('"use client";\nexport default function View() { return <WorkflowForm '
            f'workflow={{workflows.{key}}} fields={{{{}}}} />; }}')
    client_view.append(view)
    body, _ = ue.compose_page(doc, _page(), tmp_path, client)
    assert len(calls) == ue.COMPILE_ROUNDS, "asked again each round"
    assert body["view"], "and kept on the last"
