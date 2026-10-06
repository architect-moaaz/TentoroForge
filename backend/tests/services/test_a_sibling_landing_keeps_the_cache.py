"""Mozato (forge-v3), 2026-10-06: a $95 build spent ~$60 writing the same
~250k-token Blueprint slice to the prompt cache again and again. The slice is
the cached head of every fan-out call and repair edit, and it carried the
Blueprint's `version`, which ticks each time a sibling's answer lands — one
changed number made the whole block a miss."""
import copy

from services.blueprint import executors as ex
from services.blueprint.service import BlueprintService


def _doc(tmp_path):
    doc = BlueprintService.create(output_dir=tmp_path, app_id="m", name="Mozato", domain="food").doc
    doc["workflows"] = [{"id": "FLOW-001", "name": "Place Order"}, {"id": "FLOW-002", "name": "Refund"}]
    return doc


def test_no_agent_is_handed_the_version_or_the_state(tmp_path):
    doc = _doc(tmp_path)
    from services.blueprint.agent_contract import AGENT_REGISTRY
    assert AGENT_REGISTRY
    for agent in AGENT_REGISTRY:
        ctx = ex.context_for(doc, agent)
        assert "version" not in ctx and "state" not in ctx, agent
        assert "application" in ctx


def test_the_cached_head_survives_a_sibling_landing(tmp_path):
    doc = _doc(tmp_path)
    later = copy.deepcopy(doc)
    later["version"] = int(doc.get("version") or 1) + 1
    later["workflows"][1]["steps"] = [{"id": "s1"}]          # a sibling's answer landed

    def head(d, subject):
        return ex._workflow_steps_prompt(d, "SYSTEM", subject, "")[1].partition(ex.CACHE_BREAK)[0]

    assert head(doc, "FLOW-001") == head(later, "FLOW-001") == head(later, "FLOW-002")


def test_every_check_of_a_build_shares_the_observers_cached_half():
    """Mozato's 78k-character request rode in each of 255 observer checks,
    uncached. It belongs to the system prompt every check of the build shares."""
    import json

    from services.blueprint.executors import _cacheable
    from services.blueprint.observer import critic_prompt

    request = "Build a food delivery marketplace. " * 400
    def check(subject):
        return critic_prompt({"scope": "subject", "userRequest": request, "agent": "workflow",
                              "application": {"name": "Mozato"}, "subject": subject,
                              "output": {"workflows": [{"id": subject}]}, "requirements": []})
    (s1, u1), (s2, u2) = check("FLOW-001"), check("FLOW-002")
    assert s1 == s2 and request.strip() in s1 and isinstance(_cacheable(s1), list)
    assert "userRequest" not in json.loads(u1) and json.loads(u2)["subject"] == "FLOW-002"


def test_a_subject_naming_no_requirements_reads_them_from_the_cached_half(tmp_path):
    """None of Mozato's 54 entities named a requirement, so every entity call
    re-sent the whole section (~8k tokens) in its own, uncached part."""
    doc = _doc(tmp_path)
    doc["requirements"] = [{"id": "REQ-001", "statement": "Customers order food"},
                           {"id": "REQ-002", "statement": "Riders deliver it"}]
    doc.setdefault("data", {})["entities"] = [{"id": "ENTITY-001", "name": "Order", "table": "orders"},
                                              {"id": "ENTITY-002", "name": "Rider", "table": "riders",
                                               "requirements": ["REQ-002"]}]
    head, _, own = ex._entity_fields_prompt(doc, "S", "ENTITY-001", "")[1].partition(ex.CACHE_BREAK)
    assert "Customers order food" in head and "Customers order food" not in own
    assert ex.ALL_REQUIREMENTS_ABOVE in own
    head2, _, own2 = ex._entity_fields_prompt(doc, "S", "ENTITY-002", "")[1].partition(ex.CACHE_BREAK)
    assert "Riders deliver it" in own2 and "Customers order food" not in own2   # names its own: those only


def test_the_cheap_first_pass_goes_back_to_high_after_a_refusal():
    """page_details and workflow_steps author at `medium`; a reply the contract
    refused is retried at `high`. Repairs and cut-off replies keep their own rules."""
    from types import SimpleNamespace as S

    r = ex.tiered_router()
    for node in ("page_details", "workflow_steps"):
        first = r.for_task(node, "x")
        assert first.effort == "medium"
        assert ex.after_refusal(first, S(node=node, feedback="refused: no FK", repair=False)).effort == "high"
        assert ex.after_refusal(first, S(node=node, feedback="", repair=False)).effort == "medium"
        assert ex.after_refusal(first, S(node=node, feedback="findings", repair=True)).effort == "medium"
        assert ex.after_refusal(first, S(node=node, feedback="Truncated: cut", repair=False)).effort == "medium"
    assert ex.after_refusal(r.for_task("entity_fields", "x"),
                            S(node="entity_fields", feedback="refused", repair=False)).effort == "medium"
    assert r.for_task("anything", "observer").effort == "medium"


def test_the_nodes_cut_off_on_mozato_have_room():
    for node in ("requirements", "data_model", "workflows", "business_rules", "analytics", "workflow_steps"):
        assert ex.tiered_router().for_task(node, "x").max_tokens == 64000, node
