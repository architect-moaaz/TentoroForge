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
