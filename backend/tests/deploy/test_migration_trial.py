"""A publish tries its migration on a copy of the live data first.

On a redeploy the build migrates real records in place, and what would lose
or corrupt them is refused (`prepare-schema.ts`). The refusal used to arrive
as a failed publish, from data the preview never had. Now the build's own
chain runs on a Neon branch of the live database first; a refusal goes to
Smith, unattended, and the publish goes on only once the copy takes it.
"""
from __future__ import annotations

import json as _json
from pathlib import Path

import pytest
import respx
from httpx import Response

from services.deploy import migration_trial as mt
from services.deploy.neon_client import NeonClient

REFUSED = {"applied": False, "reason": "`tsx src/db/prepare-schema.ts` failed: …",
           "lines": ["[prepare-schema] the database cannot take the definition as it is:",
                     "  - menu_items.price cannot become integer: values such as \"twelve\" will not convert"]}
TAKEN = {"applied": True, "reason": "", "lines": []}


class _Neon:
    def __init__(self, *, fail: bool = False):
        self.made, self.deleted, self.fail = [], [], fail

    async def create_branch(self, project_id, name):
        if self.fail:
            raise RuntimeError("Neon is down")
        self.made.append((project_id, name))
        return {"branch_id": f"br_{len(self.made)}", "database_url": f"postgres://copy-{len(self.made)}"}

    async def delete_branch(self, project_id, branch_id):
        self.deleted.append((project_id, branch_id))


def _chain(*outcomes):
    seen = []

    def run(app_root, url, *, extra_env=None):
        seen.append((str(app_root), url, dict(extra_env or {})))
        return outcomes[len(seen) - 1]
    run.seen = seen
    return run


@pytest.mark.asyncio
async def test_the_chain_runs_on_a_copy_kept_as_a_redeploy_keeps_it_and_the_copy_is_removed(tmp_path):
    neon, chain = _Neon(), _chain(TAKEN)
    out = await mt.trial(neon, "np_1", tmp_path / "app", chain=chain)
    assert out == {"ran": True, "ok": True, "reason": "", "lines": []}
    assert chain.seen == [(str(tmp_path / "app"), "postgres://copy-1", {"FORGE_KEEP_DB_STATE": "1"})]
    assert neon.deleted == [("np_1", "br_1")]


@pytest.mark.asyncio
async def test_the_copy_is_removed_even_when_the_chain_breaks(tmp_path):
    neon = _Neon()

    def boom(*a, **k):
        raise OSError("npx missing")
    with pytest.raises(OSError):
        await mt.trial(neon, "np_1", tmp_path, chain=boom)
    assert neon.deleted == [("np_1", "br_1")]


@pytest.mark.asyncio
async def test_no_copy_means_no_trial_and_the_publish_is_not_stopped_by_it(tmp_path):
    out = await mt.ensure_publishable(_Neon(fail=True), "np_1", tmp_path, chain=_chain(),
                                      run_turn=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no turn")))
    assert out["ok"] and not out["ran"]


@pytest.mark.asyncio
async def test_a_refusal_goes_to_smith_unattended_and_the_copy_is_asked_again(tmp_path):
    asks = []

    def smith(project_id, output_dir, message, *, max_steps, unattended):
        asks.append((project_id, output_dir, message, unattended))
        return {"answer": "Kept price as text.", "edited_paths": ["app/src/db/schema/menu_item.ts"]}

    said = []
    out = await mt.ensure_publishable(_Neon(), "np_1", tmp_path, app_project_id="p1", chain=_chain(REFUSED, TAKEN),
                                      run_turn=smith, say=said.append)
    assert out["ok"] and out["fixed"]
    assert len(asks) == 1 and asks[0][0] == "p1" and asks[0][3] is True
    assert "values such as \"twelve\"" in asks[0][2] and "never delete or rewrite them" in asks[0][2]
    assert said and "every record is kept" in said[0]


@pytest.mark.asyncio
async def test_what_still_does_not_fit_stops_the_publish_with_the_records_named(tmp_path):
    out = await mt.ensure_publishable(_Neon(), "np_1", tmp_path, chain=_chain(REFUSED, REFUSED, REFUSED),
                                      run_turn=lambda *a, **k: {"answer": "tried", "edited_paths": ["x"]})
    assert not out["ok"] and out["ran"] and not out["fixed"]
    assert any("twelve" in l for l in out["lines"])


@pytest.mark.asyncio
async def test_neon_branch_is_a_copy_of_the_default_with_its_own_endpoint() -> None:
    async with respx.mock(assert_all_called=True) as rmock:
        made = rmock.post("https://console.neon.tech/api/v2/projects/np_1/branches").mock(
            return_value=Response(201, json={"branch": {"id": "br_9"},
                                             "connection_uris": [{"connection_uri": "postgres://copy"}]}))
        gone = rmock.delete("https://console.neon.tech/api/v2/projects/np_1/branches/br_9").mock(
            return_value=Response(200, json={"branch": {"id": "br_9"}}))
        c = NeonClient(api_key="nk", org_id="org-x")
        try:
            got = await c.create_branch("np_1", "forge-trial-1")
            await c.delete_branch("np_1", "br_9")
        finally:
            await c.close()
    assert got == {"branch_id": "br_9", "database_url": "postgres://copy"}
    body = _json.loads(made.calls.last.request.content)
    assert body == {"branch": {"name": "forge-trial-1"}, "endpoints": [{"type": "read_write"}]}
    assert gone.called


def test_smith_is_told_a_data_rule_is_kept_by_the_data():
    """'Dish names must be unique' became a stated rule nothing enforced
    (2026-10-02): the field's own `unique` is what the database keeps."""
    from services.smith.loop import _PROMPT
    assert "A RULE ABOUT THE DATA IS KEPT BY THE DATA" in _PROMPT
    assert "`unique`" in _PROMPT and "set with `set_field`" in _PROMPT and "not `add_rule`" in _PROMPT



DUPES = {"applied": False, "reason": "prepare refused",
         "lines": ["  - food_items.name must be unique, and the rows already there are not: name=\"Paneer Tikka\" (2 rows)"]}


def _write_doc(out, unique):
    import json
    p = Path(out) / ".forge" / "blueprint"
    p.mkdir(parents=True, exist_ok=True)
    (p / "current.json").write_text(json.dumps({"data": {"entities": [{"name": "FoodItem", "fields": [
        {"name": "name", "type": "string", "required": True, "unique": unique}]}]}}))


@pytest.mark.asyncio
async def test_the_owners_rule_is_not_undone_to_fit_their_records_they_are_asked(tmp_path):
    """'Dish names must be unique' and two live 'Paneer Tikka's: Smith removed
    the rule and the publish went on (2026-10-02). Now the rule stays, nothing
    changes, and the owner gets the records and the choices."""
    _write_doc(tmp_path, True)
    asks = []

    def smith(project_id, output_dir, message, **k):
        asks.append(message)
        return {"answer": "Two live dishes are both called Paneer Tikka. Rename one in the app, "
                          "or say names may repeat.", "edited_paths": []}
    neon = _Neon()
    out = await mt.ensure_publishable(neon, "np_1", tmp_path, chain=_chain(DUPES), run_turn=smith)
    assert not out["ok"] and "Rename one" in out["settle"]
    assert "NEVER undo a rule the owner asked for" in asks[0]
    assert len(neon.made) == 1, "the same definition is not tried twice"


@pytest.mark.asyncio
async def test_what_a_repair_did_to_the_fields_is_said(tmp_path):
    _write_doc(tmp_path, True)

    def relaxes(project_id, output_dir, message, **k):
        _write_doc(output_dir, False)
        return {"answer": "Changed the kinds of record it keeps.", "edited_paths": ["x"]}
    out = await mt.ensure_publishable(_Neon(), "np_1", tmp_path, chain=_chain(DUPES, TAKEN), run_turn=relaxes)
    assert out["ok"] and out["changed"] == "FoodItem.name is no longer unique"


def test_field_changes_in_words():
    before = {"data": {"entities": [{"name": "Order", "fields": [
        {"name": "total", "type": "integer", "required": True}, {"name": "note", "type": "string"}]}]}}
    after = {"data": {"entities": [{"name": "Order", "fields": [
        {"name": "total", "type": "numeric"}, {"name": "status", "type": "string"}]}]}}
    assert mt.what_changed(before, after) == [
        "Order.note was removed", "Order.status was added",
        "Order.total is no longer required", "Order.total changed from integer to numeric"]
