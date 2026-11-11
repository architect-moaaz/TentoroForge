"""A sensitive field's `readers` written by a role's display name are that
role. The session carries the role's `name`; kkb5mzo3 (CARES) listed "Front
Office Manager", "Income Audit", "F&B Manager" for `FrontOfficeManager` & co,
and every one of them read `••••••••` — the evidence link became
`/cases/••••••••`, a 404 (2026-11-11).

Three places: the contract writes the role's name and refuses a reader that
is no role; the projection writes role names into `sensitive-columns.ts`; the
runtime matches the same spellings, so a manifest generated before this fix
still unmasks."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from services.blueprint import agent_contract as ac
from services.blueprint.ids import resolve_role, role_spellings
from services.blueprint.projection import project_sensitive_columns, sensitive_columns

ROOT = Path(__file__).resolve().parents[2]

ROLES = [{"id": "ROLE-001", "name": "FrontOfficeManager", "permissions": ["PERM-1"]},
         {"id": "ROLE-002", "name": "IncomeAudit", "permissions": ["PERM-1"]},
         {"id": "ROLE-003", "name": "FBManager", "permissions": ["PERM-1"]},
         {"id": "ROLE-004", "name": "GlobalFinanceDirector", "permissions": ["PERM-1"]},
         {"id": "ROLE-005", "name": "Guest", "permissions": ["PERM-1"]}]
PERMS = [{"id": "PERM-1", "action": "read", "subject": "ENTITY-001"}]
DISPLAY = ["Front Office Manager", "Income Audit", "F&B Manager", "Global Finance Director"]
NAMES = ["FBManager", "FrontOfficeManager", "GlobalFinanceDirector", "IncomeAudit"]


def _field(readers):
    return {"name": "guestEmail", "type": "string", "sensitive": True, "mask": "email", "readers": list(readers)}


def _doc(readers):
    return {"roles": ROLES, "permissions": PERMS,
            "data": {"entities": [{"id": "ENTITY-001", "name": "Case", "table": "cases", "fields": [_field(readers)]}]}}


def _reply(readers):
    body = {"name": "Case", "fields": [_field(readers)]}
    return ac.AgentResult(task_id="t", agent="data_model",
                          proposals=[ac.ArtifactProposal(section="data.entities", natural_key="Case", body=body)]), body


# ── the spelling ─────────────────────────────────────────────────────────

def test_a_display_name_and_a_role_name_are_spelled_alike():
    for shown, name in zip(DISPLAY, ["FrontOfficeManager", "IncomeAudit", "FBManager", "GlobalFinanceDirector"]):
        assert role_spellings(shown) & role_spellings(name), (shown, name)
    assert role_spellings("F&B Manager") & role_spellings("FAndBManager")
    assert not role_spellings("Front Office Manager") & role_spellings("BackOfficeManager")


def test_a_spelling_resolves_to_one_role_or_none():
    assert resolve_role("front office manager", ROLES)["name"] == "FrontOfficeManager"
    assert resolve_role("ROLE-002", ROLES)["name"] == "IncomeAudit"
    assert resolve_role("Night Auditor", ROLES) is None
    twins = [{"id": "R1", "name": "FBManager"}, {"id": "R2", "name": "FAndBManager"}]
    assert resolve_role("F&B Manager", twins) is None  # names two roles: no guess
    assert resolve_role("FBManager", twins)["id"] == "R1"  # an exact name is that role


# ── at write time ────────────────────────────────────────────────────────

def test_the_contract_writes_display_name_readers_as_role_names():
    result, body = _reply(DISPLAY + ["*"])
    ac.check_entity_fields(result, {"roles": ROLES})
    assert body["fields"][0]["readers"] == ["FrontOfficeManager", "IncomeAudit", "FBManager",
                                            "GlobalFinanceDirector", "*"]


def test_the_contract_resolves_roles_this_same_reply_makes():
    result, body = _reply(["Front Office Manager"])
    result.proposals.append(ac.ArtifactProposal(section="roles", natural_key="FrontOfficeManager",
                                                body={"name": "FrontOfficeManager"}))
    ac.check_entity_fields(result, {})
    assert body["fields"][0]["readers"] == ["FrontOfficeManager"]


def test_a_reader_that_is_no_role_is_refused_and_named():
    result, body = _reply(["Front Office Manager", "Night Auditor"])
    with pytest.raises(ac.InvalidEntityFields) as raised:
        ac.check_entity_fields(result, {"roles": ROLES})
    said = str(raised.value)
    assert "Case.guestEmail" in said and "'Night Auditor'" in said and "FrontOfficeManager" in said
    # The safe way through drops the stranger and keeps the role it resolved.
    settled = raised.value.settle()
    assert body["fields"][0]["readers"] == ["FrontOfficeManager"]
    assert any("Night Auditor" in s for s in settled)


def test_readers_before_any_role_exists_are_refused_and_left_out_on_settling():
    result, body = _reply(["AdminUser"])
    with pytest.raises(ac.InvalidEntityFields) as raised:
        ac.check_entity_fields(result, {})
    assert "no role exists yet" in str(raised.value)
    raised.value.settle()
    assert "readers" not in body["fields"][0]


# ── in the generated app ─────────────────────────────────────────────────

def test_the_manifest_lists_role_names_for_display_name_readers(tmp_path):
    assert sensitive_columns(_doc(DISPLAY))["Case"]["guestEmail"]["readers"] == NAMES
    project_sensitive_columns(_doc(DISPLAY), tmp_path)
    text = (tmp_path / "src/lib/sensitive-columns.ts").read_text()
    manifest = json.loads(re.search(r"> = (\{.*\}) as const;", text, re.S).group(1))
    assert manifest["Case"]["guestEmail"]["readers"] == NAMES
    assert "Front Office Manager" not in text


_ENGINE = ROOT / "templates/runtime/data-engine.ts"


def _runtime_unmask(readers: list[str], role: str | None) -> bool:
    src = _ENGINE.read_text()
    fns = [re.search(rf"function {n}\(.*?\n}}\n", src, re.S).group(0) for n in ("_canReaderUnmask", "_roleSpellings")]
    script = "\n".join(re.sub(r"(\w+)(\??): [^,)=]+(?=[,)])", r"\1", f) for f in fns)  # drop param types
    script = re.sub(r"\): \w+ \{", ") {", script)  # drop return types
    script += f"\nconsole.log(JSON.stringify(_canReaderUnmask({{readers: {json.dumps(readers)}}}, {json.dumps(role)})));"
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_runtime_unmasks_a_display_name_reader_for_the_session_role():
    """An app generated before the fix keeps its display names in the manifest."""
    assert _runtime_unmask(DISPLAY, "FrontOfficeManager") is True
    assert _runtime_unmask(DISPLAY, "FBManager") is True
    assert _runtime_unmask(["F&B Manager"], "FAndBManager") is True
    assert _runtime_unmask(DISPLAY, "GlobalFinanceDirector") is True
    assert _runtime_unmask(["FrontOfficeManager"], "FrontOfficeManager") is True
    assert _runtime_unmask(DISPLAY, "BackOfficeManager") is False
    assert _runtime_unmask(DISPLAY, None) is False
    assert _runtime_unmask([], "FrontOfficeManager") is False
    assert _runtime_unmask(["*"], "Anyone") is True
