"""Every declared page kind is judged by the floor written for that kind.

Measured across the Blueprint's eighteen-pattern enum, the family map was wrong
in both directions at once:

  * ELEVEN patterns matched nothing and fell through to `_family_of`'s
    `dashboard` default, so `settings`, `configuration`, `calendar`,
    `search_results`, `data_explorer` and `document_workspace` were each
    required to carry KPIs, a chart and an activity feed. A security-settings
    page cannot satisfy that, so it was refused every time — six of the
    fourteen routes that 404ed on a real application.
  * FIVE more — `entity_list`, `record_workspace`, `master_detail`, `wizard`,
    `approval_inbox`, which is most of what any application is made of —
    matched neither table, so `page_kind_findings` returned "not my rule" and
    they were held to no floor at all.

Only `dashboard` and `kanban` were judged correctly.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from services.a2ui_authority import UNCLASSIFIED_FAMILY, _family_of
from services.page_kind_anatomy import page_family

_CONTRACT = (pathlib.Path(__file__).resolve().parents[2]
             / "contracts" / "blueprint.schema.json")

FAMILIES = {"dashboard", "collection", "record", "form"}


def _declared_patterns() -> list[str]:
    doc = json.loads(_CONTRACT.read_text(encoding="utf-8"))
    return doc["properties"]["pages"]["items"]["properties"]["pattern"]["enum"]


@pytest.mark.parametrize("pattern", _declared_patterns())
def test_every_declared_pattern_has_a_family(pattern):
    """A pattern absent from the map is a page judged by a floor written for a
    different kind of screen. This fails rather than letting a newly added
    pattern default into one."""
    fam = page_family(pattern)
    assert fam in FAMILIES, (
        f"{pattern!r} has no family, so it will be judged as "
        f"{UNCLASSIFIED_FAMILY!r} — add it to page_kind_anatomy._FAMILY")


def test_the_kinds_that_were_refused_for_not_being_dashboards():
    """The six that 404ed. A settings page is a form; an audit log is a
    collection; neither owes anyone a chart."""
    assert _family_of("settings") == "form"
    assert _family_of("configuration") == "form"
    assert _family_of("calendar") == "collection"
    assert _family_of("search_results") == "collection"
    assert _family_of("data_explorer") == "collection"
    assert _family_of("document_workspace") == "record"


def test_the_kinds_that_were_judged_by_nothing():
    """Most of what an application is made of."""
    for pattern in ("entity_list", "approval_inbox", "record_workspace",
                    "master_detail", "wizard"):
        assert page_family(pattern) in FAMILIES, pattern


def test_a_real_dashboard_is_still_a_dashboard():
    """The floor exists and three patterns genuinely owe it."""
    for pattern in ("dashboard", "analytics", "command_center"):
        assert _family_of(pattern) == "dashboard"


def test_one_table_answers_the_question():
    """`a2ui_authority` kept a second, partial copy — seven entries against
    eighteen — consulted only when `page_family` had no answer, which was most
    of the time. The two disagreed by omission, so nothing looked wrong."""
    import inspect

    from services import a2ui_authority

    assert not hasattr(a2ui_authority, "_PATTERN_FAMILY")
    src = inspect.getsource(a2ui_authority._family_of)
    assert "page_family(kind) or UNCLASSIFIED_FAMILY" in src


def test_the_fallback_is_not_the_strictest_floor():
    """It was `dashboard` — the most demanding there is — so an unrecognised
    kind was required to carry KPIs, a chart and an activity feed. Whatever
    the default is, it must not be that."""
    assert UNCLASSIFIED_FAMILY in FAMILIES
    assert UNCLASSIFIED_FAMILY != "dashboard"


def test_the_generic_words_outside_the_pipeline_still_work():
    """Callers that predate the pattern enum pass `list`, `detail`, `form`."""
    assert page_family("list") == "collection"
    assert page_family("detail") == "record"
    assert page_family("form") == "form"
