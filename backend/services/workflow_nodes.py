"""The one shape of a workflow node, for every deterministic producer.

Three generators (the Blueprint projection, the CRUD generator and the
completeness floor) each carried a private ``_node`` helper, and each drifted
the same way: nodes laid out left-to-right on ``y = 0`` with no
``data.nodeType``. The editor switches on ``data.nodeType`` to pick the styled
node component and the properties panel, so a node without it renders as
React Flow's unstyled default box; and its handles are top (in) / bottom
(out), so a left-to-right row draws every edge as a loop from one node's
underside back over the next node's top.

The LLM-facing producers (``workflow_step_translator``, ``generate.py``'s
``add_node``) already emit this shape. This module is the single definition
so a deterministic producer cannot drift from it again.
"""
from __future__ import annotations

#: Column every node sits in, and the row pitch — the same numbers the step
#: translator and the plan-sync generator use, so a workflow looks the same
#: whichever producer wrote it.
NODE_X = 250
ROW_HEIGHT = 120


def workflow_node(node_id: str, ntype: str, row: int, config: dict, label: str) -> dict:
    """Build one node in the editor/engine shape.

    ``row`` is the node's position in the top-to-bottom chain (0 = trigger).
    ``ntype`` must be a runtime node type — the editor and the executor both
    dispatch on it — and it is stamped into ``data.nodeType`` and
    ``config.nodeType`` because that is where the editor reads it.
    """
    return {
        "id": node_id,
        "type": ntype,
        "position": {"x": NODE_X, "y": row * ROW_HEIGHT},
        "data": {
            "label": label,
            "nodeType": ntype,
            "config": {**config, "nodeType": ntype},
            "status": "idle",
        },
    }
