"""A retry that is not told what went wrong is just the same request again.

`build_prompt` grew a branch per node that needed special framing — workflows,
page_contracts, figma_intelligence, the A2UI catalog — and each one appended
`feedback` before returning. The generic tail, which every node WITHOUT a
branch of its own falls through to, did not.

So `data_model` failed contract validation, the orchestrator caught it, set
`feedback` and retried — with a byte-identical prompt. It emitted the same
`references: ""` and the node failed twice for one bad field.

The property, asserted per node rather than against the source text: if a call
carries feedback, the prompt repeats it. A new node with no branch of its own
inherits that by default, and a new branch that forgets fails here.
"""
import pytest

from services.blueprint.executors import DAG, build_prompt

REJECTION = "data/entities/0/fields/0/references: '' does not match '^ENTITY-'"

#: Nodes that answer on the generic path — none has a branch in `build_prompt`,
#: which is exactly why they regressed. Skipped rather than hard-coded if the
#: DAG is renamed, so this test never fails for the wrong reason.
GENERIC_NODES = ["data_model", "business_rules", "apis", "security"]


def _doc() -> dict:
    return {
        "application": {"name": "Contact Book", "domain": "internal tools"},
        "requirements": [],
        "data": {"entities": [], "relationships": [], "constraints": []},
        "pages": [],
        "workflows": [],
    }


@pytest.mark.parametrize("node", GENERIC_NODES)
def test_a_rejected_attempt_is_quoted_back_to_the_author(node):
    if node not in DAG:
        pytest.skip(f"{node} is no longer a DAG node")

    _system, user = build_prompt(_doc(), node, feedback=REJECTION)

    assert REJECTION in user, (
        f"{node} retried without being told what was rejected — its second "
        f"attempt is the same request as its first"
    )


@pytest.mark.parametrize("node", GENERIC_NODES)
def test_a_first_attempt_carries_no_rejection(node):
    """Attempt one has nothing to be told, and must not be primed with one."""
    if node not in DAG:
        pytest.skip(f"{node} is no longer a DAG node")

    _system, user = build_prompt(_doc(), node, feedback="")

    assert "previous attempt was rejected" not in user
