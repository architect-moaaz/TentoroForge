"""A chart's group-by dimension must be readable, or there is no chart.

Why this exists
---------------
A2UI declares a chart's MEASURE and never its DIMENSION — a real surface says
`series: [{"key": "count", "label": "Products"}]` on a component whose id is
`categoryChart`, and nothing anywhere names `category`. The binder had to
invent the axis and fell back to `id`.

Grouping by a uuid primary key draws one bar per row labelled with a uuid. The
dashboard floor catches it (`dashboard_groupby_unreadable`) and, because the
floor is all-or-nothing, threw away a 95-node composition over 3 such charts —
the app then shipped a 13-node stub titled "Dashboard Page". So a bad default
here does not degrade one widget, it loses the whole page.

The rule this pins: pick a dimension a human can read, or emit no chart at all.
An absent chart is honest; a uuid axis is not. The fallback order mirrors what
the floor will accept, so the binder can never author something the gate is
guaranteed to reject.
"""

from services.a2ui_to_forge import _Binder

COLS = {
    "Product": [
        {"name": "id", "type": "uuid"},
        {"name": "name", "type": "varchar"},
        {"name": "categoryId", "type": "uuid", "fk": "Category"},
        {"name": "status", "type": "varchar", "enum": ["active", "discontinued"]},
    ],
    # No enum anywhere — the case that used to fall through to `id`.
    "Warehouse": [
        {"name": "id", "type": "uuid"},
        {"name": "name", "type": "varchar"},
        {"name": "region", "type": "varchar"},
        {"name": "notes", "type": "text"},
    ],
    # Nothing groupable at all: key, free text, and a foreign key.
    "Attachment": [
        {"name": "id", "type": "uuid"},
        {"name": "title", "type": "varchar"},
        {"name": "ownerId", "type": "uuid", "fk": "User"},
        {"name": "payload", "type": "jsonb"},
    ],
}


def _binder(entities=None):
    return _Binder({"entities": {k: {"columns": v} for k, v in
                                 (entities or COLS).items()}}, {})


def test_an_enum_is_the_preferred_axis():
    assert _binder()._group_column("Product") == "status"


def test_a_named_category_column_is_used_when_no_enum_exists():
    """`region` is a real dimension; the old code returned `id` here."""
    assert _binder()._group_column("Warehouse") == "region"


def test_the_component_label_steers_the_choice():
    """A component called `categoryChart` means category, even though the
    entity also carries a perfectly groupable `status`."""
    cols = {"Product": COLS["Product"] + [{"name": "category", "type": "varchar"}]}
    assert _binder(cols)._group_column("Product", hint="categoryChart") == "category"


def test_a_primary_key_is_never_the_axis():
    for entity in COLS:
        assert _binder()._group_column(entity) != "id"


def test_a_foreign_key_is_never_the_axis():
    """One bar per uuid with uuid labels — the floor rejects it by name."""
    assert _binder()._group_column("Product") != "categoryId"


def test_free_text_is_never_the_axis():
    """`name` / `title` group one row per row: a list drawn as a chart."""
    assert _binder()._group_column("Warehouse") not in ("name", "notes")


def test_nothing_groupable_yields_no_column():
    """The honest answer. The caller emits no chart rather than a uuid axis."""
    assert _binder()._group_column("Attachment") is None


def test_an_unknown_entity_yields_no_column():
    assert _binder()._group_column("Nope") is None
