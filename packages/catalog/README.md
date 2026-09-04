# @tentoroforge/catalog

The Forge catalogs: what an application is built *from*, kept apart from the
Blueprint (what an application *is*) and from the agents that author it. An
agent pulls the catalog it needs for the task in hand, and only that one.

| Catalog | Source of truth | Emitted copies |
| --- | --- | --- |
| Workflow nodes | `workflow-nodes.json` (here) | `backend/contracts/workflow-node-catalog.json`, `frontend/src/catalog/workflow-nodes.json` |
| UI components | `packages/library/src/buildDefaultRegistry.tsx` | `backend/contracts/component-catalog.json` |

## Workflow nodes

One entry per node the workflow editor's palette offers and the runtime engine
executes. Each carries:

- `type` — the runtime `NodeType`; the editor and the executor both dispatch on it.
- `variantKey` / `variants` — for nodes whose behaviour is chosen by one config
  key (`trigger.type`, `action.actionType`), the values that key may take.
- `config.required` — groups of alternative keys; a node is configured when
  every group has at least one present key. The workflow agent fills these; the
  Blueprint refuses a step that leaves one empty.
- `config.defaults` — what a fresh node of that kind carries.
- `handles` — whether the node takes an incoming edge, an outgoing edge, and an
  `else` branch.

After editing: `npm run emit --workspace=packages/catalog`.
