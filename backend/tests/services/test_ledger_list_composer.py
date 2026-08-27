"""Tests for the Slice-3 ledger-list collection composer + KNOWN_SHAPES
widening.

The composer contract:

  * ``KNOWN_SHAPES`` now accepts ``ledger-list`` and ``kanban`` — the two
    shapes banking-platform relies on.
  * The ``ledger-list`` composer emits a ``Table`` bound to the entity's
    ``op:"list"`` dataSource ordered newest-first, with columns:
      - primary (description) — no format
      - every ``type:"money"`` column — ``format:"currency"``, right-aligned
      - status column (if any) — ``format:"badge"``
      - a trailing timestamp column — ``format:"datetime"``, right-aligned
    plus a companion ``op:"series" agg.fn:"running_sum"`` dataSource per
    money column so a client can render running balance.
  * The Table carries ``data-row-treatment:"compact"`` + ``data-shape:
    "ledger-list"`` so the renderer picks the row-borders style.
"""
from __future__ import annotations

from services.apply_collection_maquette import _build_collection_node
from services.archetype_vocabulary import KNOWN_SHAPES


# ── KNOWN_SHAPES widening ──────────────────────────────────────────────────

def test_known_shapes_includes_ledger_list():
    assert "ledger-list" in KNOWN_SHAPES


def test_known_shapes_includes_kanban():
    assert "kanban" in KNOWN_SHAPES


def test_known_shapes_still_has_originals():
    for s in ("table", "card-list", "card-grid", "schedule-grid"):
        assert s in KNOWN_SHAPES


# ── ledger-list composer ──────────────────────────────────────────────────

def _tx_columns() -> dict[str, str]:
    """Column-type map matching a real banking Transaction schema."""
    return {
        "id": "uuid",
        "amount": "money",
        "description": "text",
        "status": "enum",
        "createdAt": "timestamp",
    }


def _tx_maquette() -> dict:
    return {
        "entity": "Transaction",
        "route": "/transactions",
        "layout": "ledger-list",
        "columns": [
            {"name": "description", "label": "Description"},
            {"name": "amount", "label": "Amount"},
            {"name": "status", "label": "Status"},
        ],
    }


def _build():
    node, ds_name, sources, used = _build_collection_node(
        entity="Transaction",
        route="/transactions",
        layout="ledger-list",
        maquette=_tx_maquette(),
        columns=_tx_columns(),
        row_treatment="compact",
    )
    return node, ds_name, sources, used


def test_ledger_list_emits_table_shape():
    node, _ds, _sources, used = _build()
    assert node is not None
    assert node["type"] == "Table"
    assert used == "ledger-list"


def test_ledger_list_carries_shape_marker():
    """The ledger-list Table announces its shape so the renderer's CSS can
    pick up the row-border-only style (no per-row card wrapper)."""
    node, _ds, _sources, _used = _build()
    assert node["props"]["data-shape"] == "ledger-list"
    assert node["props"]["data-row-treatment"] == "compact"


def test_ledger_list_columns_have_correct_formats():
    node, _ds, _sources, _used = _build()
    cols = {c["key"]: c for c in node["props"]["columns"]}
    # Money column right-aligned + currency-formatted.
    assert cols["amount"]["format"] == "currency"
    assert cols["amount"]["align"] == "right"
    # Status column as badge.
    assert cols["status"]["format"] == "badge"
    # Timestamp appended even though the maquette didn't list it.
    assert "createdAt" in cols
    assert cols["createdAt"]["format"] == "datetime"
    assert cols["createdAt"]["align"] == "right"


def test_ledger_list_orders_newest_first():
    """Every ledger sorts DESC by createdAt so the freshest row leads —
    encoded on the list dataSource's orderBy."""
    _node, _ds, sources, _used = _build()
    list_source = sources[0]
    assert list_source["op"] == "list"
    assert list_source["orderBy"] == [{"field": "createdAt", "dir": "desc"}]


def test_ledger_list_emits_running_sum_datasource_per_money_column():
    _node, ds_name, sources, _used = _build()
    running = [s for s in sources if s.get("op") == "series"]
    assert len(running) == 1
    r = running[0]
    assert r["name"] == f"{ds_name}RunningAmount"
    assert r["entity"] == "Transaction"
    assert r["agg"] == {"fn": "running_sum", "field": "amount"}
    assert r["orderByCol"] == "createdAt"


def test_ledger_list_binds_rows_to_list_source():
    node, ds_name, _sources, _used = _build()
    assert node["props"]["rows"] == f"{{{{{ds_name}}}}}"


def test_ledger_list_multiple_money_columns_emit_multiple_running_sources():
    columns = {
        "id": "uuid",
        "debit": "money",
        "credit": "money",
        "description": "text",
        "createdAt": "timestamp",
    }
    maquette = {
        "entity": "Transaction",
        "route": "/transactions",
        "layout": "ledger-list",
        "columns": [
            {"name": "description"},
            {"name": "debit"},
            {"name": "credit"},
        ],
    }
    _node, ds_name, sources, _used = _build_collection_node(
        entity="Transaction",
        route="/transactions",
        layout="ledger-list",
        maquette=maquette,
        columns=columns,
        row_treatment="compact",
    )
    running = sorted(s["name"] for s in sources if s.get("op") == "series")
    assert running == [f"{ds_name}RunningCredit", f"{ds_name}RunningDebit"]


# ── Table money-column defaulter in deterministic_pages.build_list_page ────

def test_deterministic_list_page_defaults_money_to_currency_format():
    """When the deterministic list-page builder emits a Table for an entity
    with money columns, those columns should default to
    ``format:"currency"``, ``align:"right"``."""
    from services.deterministic_pages import build_list_page

    page = build_list_page(
        entity="Payment",
        columns={
            "id": {"type": "uuid"},
            "amount": {"type": "money"},
            "note": {"type": "text"},
        },
        route="/payments",
        design_spec=None,
    )
    # The Table node lives on the page root; find it.
    def _iter(n):
        if isinstance(n, dict):
            yield n
            for v in n.values():
                yield from _iter(v)
        elif isinstance(n, list):
            for v in n:
                yield from _iter(v)

    table = next((n for n in _iter(page) if isinstance(n, dict) and n.get("type") == "Table"), None)
    assert table is not None
    cols = {c["key"]: c for c in table["props"]["columns"]}
    assert "amount" in cols, f"amount col missing (cols were {list(cols)})"
    assert cols["amount"]["format"] == "currency"
    assert cols["amount"]["align"] == "right"
    # Non-money columns stay unformatted — check any that survived the
    # display-column filter beside `amount`.
    non_money = [c for k, c in cols.items() if k != "amount"]
    for c in non_money:
        assert c.get("format") != "currency"
