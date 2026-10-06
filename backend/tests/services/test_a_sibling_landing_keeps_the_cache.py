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
