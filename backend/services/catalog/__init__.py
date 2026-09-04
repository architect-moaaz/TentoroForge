"""The Forge catalogs — what an application is built *from*.

Kept apart from the Blueprint (what an application *is*) and from the agents
that author it, so an agent pulls the catalog its task needs and nothing else:
the page agents read the UI component catalog, the workflow agent reads the
workflow node catalog. Sources of truth and emitted copies are described in
``packages/catalog/README.md``.
"""
from services.catalog.workflow_nodes import (  # noqa: F401
    WORKFLOW_NODE_CATALOG_PATH,
    WorkflowNodeCatalog,
    workflow_nodes,
)
