"""The binding contract is derived from REALITY (extracted registry) and fed to
the page agent so it references the real entity, not a guessed short name."""
import json

from services.binding_contract import (
    derive_binding_contract, binding_contract_block, save_binding_contract,
)


def _app(tmp_path):
    (tmp_path / "registry.json").write_text(json.dumps({
        "entities": {
            "Member": {"fields": {"id": {"type": "uuid"}, "planId": {"type": "uuid"},
                                  "ownerId": {"type": "uuid"}, "name": {"type": "varchar"}}},
            "MembershipPlan": {"fields": {"id": {"type": "uuid"}, "name": {"type": "varchar"}}},
        },
        "relations": [{"from_entity": "Member", "to_entity": "MembershipPlan", "type": "many-to-one"}],
    }))
    wf = tmp_path / "workflows"
    wf.mkdir()
    (wf / "CreateMember.json").write_text('{"name": "CreateMember"}')
    (wf / "UpdateMember.json").write_text('{"name": "UpdateMember"}')
    return tmp_path


def test_derives_fk_binding_from_reality(tmp_path):
    _app(tmp_path)
    c = derive_binding_contract(str(tmp_path))
    m = c["Member"]
    fk = {b["field"]: b for b in m["fkBindings"]}
    assert "planId" in fk
    assert fk["planId"]["targetEntity"] == "MembershipPlan"     # real entity, not "Plan"
    assert fk["planId"]["source"] == "membershipPlans"          # resolvable slug
    assert fk["planId"]["labelField"] == "name"
    # owner FK is excluded (auto-set, not a user dropdown)
    assert "ownerId" not in fk
    assert m["createWorkflow"] == "CreateMember"
    assert m["updateWorkflow"] == "UpdateMember"


def test_block_hands_page_agent_exact_references(tmp_path):
    _app(tmp_path)
    block = binding_contract_block(str(tmp_path), "Member")
    assert "MembershipPlan" in block
    assert '"source": "membershipPlans"' in block
    assert '"label": "name"' in block
    assert "CreateMember" in block and "UpdateMember" in block
    # nothing for an unknown entity
    assert binding_contract_block(str(tmp_path), "Nope") == ""


def test_save_and_reload(tmp_path):
    _app(tmp_path)
    save_binding_contract(str(tmp_path))
    saved = json.loads((tmp_path / "contracts" / "binding-contract.json").read_text())
    assert saved["Member"]["fkBindings"][0]["targetEntity"] == "MembershipPlan"


def test_missing_registry_safe(tmp_path):
    assert derive_binding_contract(str(tmp_path)) == {}
    assert binding_contract_block(str(tmp_path), "Member") == ""
