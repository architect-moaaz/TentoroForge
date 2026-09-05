"""Chrome is what every screen shares; it belongs to the shell, not the page.

On a real 15-screen design the sidebar subtree had ONE fingerprint across all
15 pages and the top bar (a breadcrumb) had eleven. Composing each frame whole
therefore put the design's rail inside every page, beside the scaffold's own
generic rail from `navigation.tree`, and — because the scaffold opens
`/[entity]/new` as a modal — a third copy inside a dialog. The design's
sidebar was on every page and was never the application's.

The rule this module implements is a definition, not a heuristic: chrome is
the subtree identical on most screens. No widths, no colours, no layer names
(this file had none). Three consequences are pinned here:

  * a single screen, or screens that share nothing, have NO chrome and compose
    exactly as before;
  * splitting never empties a page — if the shared subtree somehow holds the
    content, the page is returned untouched;
  * what the rail says is read in the designer's order: brand, then group
    headings, then destinations under them.
"""
import pytest

from services.figma.chrome import (
    describe, fingerprint, navigation_from, shared_chrome, split,
)


# ----------------------------------------------------------------- fixtures

def _t(kind, *children, **props):
    return {"type": kind, "props": props, "children": list(children)}


def _rail():
    """The design's sidebar: brand, headings, destinations with glyph labels."""
    return _t("Stack",
              _t("Text", content="Criterion"),
              _t("Text", content="Case Management"),
              _t("Text", content="OVERVIEW"),
              _t("Button", label="⬡Dashboard", navigate="/"),
              _t("Button", label="⌂Front Desk", navigate="/front-desk"),
              _t("Text", content="CASES"),
              _t("Button", label="+New Case", navigate="/cases/new"),
              _t("Text", content="◎Guest Self-Service"),      # unbound, glyph
              className="bg-[#110f0c] w-[240px] h-full")


def _screen(title, *body):
    """Dev Mode's shape: Stack > Stack(bg) > Row > [rail, page]."""
    page = _t("Stack", _t("Heading", content=title), *body,
              className="flex flex-col w-[1147px]")
    return _t("Stack",
              _t("Stack", _t("Row", _rail(), page, className="flex"),
                 className="bg-[#f7f3eb] w-full"),
              className="relative size-full")


SCREENS = [_screen("Operations Dashboard", _t("Text", content="Open cases 4")),
           _screen("Cases", _t("Text", content="CAS-2024-0441")),
           _screen("Approvals", _t("Text", content="Pending 3")),
           _screen("Audit Log", _t("Text", content="2 Dec 2024"))]


# --------------------------------------------------------- the definition

def test_the_rail_is_the_one_subtree_every_screen_shares():
    chrome = shared_chrome(SCREENS)
    assert fingerprint(_rail()) in chrome


def test_the_page_body_is_not_chrome():
    chrome = shared_chrome(SCREENS)
    body = SCREENS[0]["children"][0]["children"][0]["children"][1]
    assert fingerprint(body) not in chrome


def test_a_whole_screen_is_never_chrome():
    """The root is excluded even though four roots share a type."""
    chrome = shared_chrome(SCREENS)
    assert not any(fingerprint(s) in chrome for s in SCREENS)


def test_one_screen_has_no_chrome():
    """Nothing to compare with — composes exactly as before."""
    assert shared_chrome(SCREENS[:1]) == set()


def test_screens_that_share_nothing_have_no_chrome():
    a = _t("Stack", _t("Text", content="only here"), _t("Text", content="x"),
           _t("Text", content="y"))
    b = _t("Stack", _t("Text", content="only there"), _t("Text", content="p"),
           _t("Text", content="q"))
    assert shared_chrome([a, b]) == set()


def test_a_shared_logo_is_not_chrome():
    """Shared but nearly wordless — decoration, not destinations."""
    logo = _t("Image", alt="")
    screens = [_t("Stack", logo, _t("Text", content=f"page {i}")) for i in range(4)]
    assert shared_chrome(screens) == set()


def test_a_majority_is_enough():
    """One screen drawn without the rail — a sign-in — must not veto it."""
    bare = _t("Stack", _t("Heading", content="Sign in"))
    assert fingerprint(_rail()) in shared_chrome(SCREENS + [bare])


def test_fingerprints_ignore_ids_and_class_noise():
    a = _rail()
    b = _rail(); b["props"]["className"] = "bg-[#110f0c] w-[239.5px]"; b["id"] = "n-1"
    assert fingerprint(a) == fingerprint(b)


# -------------------------------------------------------------- splitting

def test_split_removes_the_rail_and_keeps_the_page():
    chrome = shared_chrome(SCREENS)
    content, removed = split(SCREENS[0], chrome)
    assert len(removed) == 1
    assert fingerprint(removed[0]) == fingerprint(_rail())
    text = " ".join(_all_labels(content))
    assert "Operations Dashboard" in text and "Open cases 4" in text
    assert "Front Desk" not in text


def test_split_unwraps_the_single_child_wrappers():
    """Stack > Stack > Row > page becomes page."""
    content, _ = split(SCREENS[0], shared_chrome(SCREENS))
    assert content["type"] == "Stack"
    assert content["children"][0]["type"] == "Heading"


def test_split_keeps_the_frames_background():
    content, _ = split(SCREENS[0], shared_chrome(SCREENS))
    assert "bg-[#f7f3eb]" in content["props"]["className"]


def test_split_drops_the_pages_fixed_width():
    """The content region fills the shell; the frame's `w-[1147px]` would
    leave a strip of nothing beside it."""
    content, _ = split(SCREENS[0], shared_chrome(SCREENS))
    assert "w-[1147px]" not in (content["props"].get("className") or "")


def test_split_with_no_chrome_is_the_identity():
    root = SCREENS[0]
    content, removed = split(root, set())
    assert content is root and removed == []


def test_split_never_empties_a_page():
    """If the only shared subtree holds everything the page says, removing it
    would remove the page. The page wins."""
    everything = _t("Stack", _t("Heading", content="A"), _t("Text", content="B"),
                    _t("Text", content="C"))
    screens = [_t("Stack", everything) for _ in range(3)]
    chrome = shared_chrome(screens)
    assert fingerprint(everything) in chrome
    content, removed = split(screens[0], chrome)
    assert content is screens[0] and removed == []


# ---------------------------------------------------- what the rail says

def test_the_rail_is_read_in_the_designers_order():
    nav = navigation_from([_rail()])
    assert nav["brand"] == ["Criterion", "Case Management"]
    assert [g["label"] for g in nav["groups"]] == ["OVERVIEW", "CASES"]


def test_destinations_keep_their_bindings_and_lose_their_glyphs():
    nav = navigation_from([_rail()])
    overview = nav["groups"][0]["items"]
    assert overview[0] == {"label": "Dashboard", "navigate": "/"}
    assert overview[1] == {"label": "Front Desk", "navigate": "/front-desk"}


def test_an_unbound_item_with_a_glyph_is_still_a_destination():
    """The binding is the application's problem; the drawing's intent is not
    in doubt."""
    cases = navigation_from([_rail()])["groups"][1]["items"]
    assert {"label": "Guest Self-Service"} in cases


def test_describe_reads_like_a_rail():
    text = describe(navigation_from([_rail()]))
    assert "Brand: Criterion / Case Management" in text
    assert "OVERVIEW: Dashboard → /, Front Desk → /front-desk" in text


# ------------------------------------------------------------------ helpers

def _all_labels(node, out=None):
    out = [] if out is None else out
    if isinstance(node, dict):
        p = node.get("props") or {}
        t = p.get("label") or p.get("content")
        if isinstance(t, str):
            out.append(t)
        for c in node.get("children") or []:
            _all_labels(c, out)
    return out
