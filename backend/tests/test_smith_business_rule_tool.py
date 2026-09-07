"""Smith can author a Business Rule (project_rules) — the tool wiring + guards.

The end-to-end DB path (row insert + rules/index.json export) is exercised
against a live Postgres separately; these tests pin the pieces that must not
regress without needing a database:
  - the tool is registered in the catalog, the dispatch table, and the
    mutating-tools gate (so it goes through confirm/verify like every write);
  - input validation rejects an incomplete rule before touching the DB;
  - the project-id is resolved from the app's .env.local.
"""
import tempfile
from pathlib import Path

from services import smith_tools
from agents import smith_agent


def test_tool_is_registered_everywhere():
    names = {t["name"] for t in smith_tools.TOOL_CATALOG}
    assert "create_business_rule" in names, "missing from TOOL_CATALOG (Smith can't see it)"
    assert "create_business_rule" in smith_tools.READONLY_HANDLERS, "missing from dispatch table"
    assert "create_business_rule" in smith_agent._MUTATING_TOOLS, (
        "must be a mutating tool so it goes through the confirm/verify gate"
    )


def test_catalog_entry_disambiguates_from_field_interaction():
    entry = next(t for t in smith_tools.TOOL_CATALOG if t["name"] == "create_business_rule")
    desc = entry["desc"].lower()
    # It must tell the model when to prefer it over set_field_interaction.
    assert "set_field_interaction" in desc
    assert "project_rules" in desc or "rules panel" in desc or "rules editor" in desc


def test_handler_rejects_incomplete_rule_without_db():
    # No name / no rule_type → applied False, and it never reaches the DB.
    d = tempfile.mkdtemp()
    Path(d, ".env.local").write_text("FORGE_PROJECT_ID=00000000-0000-0000-0000-000000000000\n", encoding="utf-8")
    r1 = smith_tools._smith_create_business_rule(d, {"rule_type": "validation", "config": {}})
    assert r1["applied"] is False and "name" in r1["reason"].lower()
    r2 = smith_tools._smith_create_business_rule(d, {"name": "x", "config": {}})
    assert r2["applied"] is False and "rule_type" in r2["reason"].lower()


def test_handler_reports_when_project_id_unresolved():
    d = tempfile.mkdtemp()  # no .env.local
    r = smith_tools._smith_create_business_rule(
        d, {"name": "x", "rule_type": "validation", "config": {"expression": "1", "errorMessage": "e"}}
    )
    assert r["applied"] is False and "forge_project_id" in r["reason"].lower()


def test_read_forge_project_id_parses_env_local():
    d = tempfile.mkdtemp()
    Path(d, ".env.local").write_text(
        'NEXTAUTH_URL=http://localhost:3000\nFORGE_PROJECT_ID="abc-123"\n'
    )
    assert smith_tools._read_forge_project_id(d) == "abc-123"


def test_sync_rule_creator_validates_type_without_db(monkeypatch):
    # Invalid rule_type must be rejected before any DB connection is attempted.
    from services import runtime_injector
    res = runtime_injector.create_project_rule_sync(
        "00000000-0000-0000-0000-000000000000",
        {"name": "x", "rule_type": "not_a_type", "config": {}},
    )
    assert res["ok"] is False and "invalid rule_type" in res["error"]
