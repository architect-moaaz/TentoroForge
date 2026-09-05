"""The workflow node catalog — the components a workflow is built from.

One entry per node the editor's palette offers and the runtime engine
executes. The workflow agent authors Blueprint steps in this vocabulary and
fills each node's declared configuration; the projection assembles nodes from
it; the executability check reads its required keys. Source of truth is
``packages/catalog/workflow-nodes.json``; the copy read here is emitted from
it and a test fails when the two drift.
"""
from __future__ import annotations

import functools
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

WORKFLOW_NODE_CATALOG_PATH = (
    Path(__file__).resolve().parents[2] / "contracts" / "workflow-node-catalog.json"
)


def _present(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, (dict, list, str)) and len(value) == 0:
        return False
    return True


@dataclass(frozen=True)
class WorkflowNodeCatalog:
    doc: dict

    # -- lookup -------------------------------------------------------------

    @property
    def nodes(self) -> dict[str, dict]:
        return {n["type"]: n for n in self.doc["nodes"]}

    @property
    def node_types(self) -> list[str]:
        return [n["type"] for n in self.doc["nodes"]]

    @property
    def categories(self) -> list[dict]:
        return list(self.doc["categories"])

    def node(self, ntype: str) -> dict | None:
        return self.nodes.get(ntype)

    def variant_key(self, ntype: str) -> str | None:
        node = self.node(ntype)
        return node.get("variantKey") if node else None

    def variants(self, ntype: str) -> dict[str, dict]:
        node = self.node(ntype) or {}
        return {v["key"]: v for v in node.get("variants") or []}

    def variant(self, ntype: str, config: dict | None) -> dict | None:
        key = self.variant_key(ntype)
        if not key:
            return None
        return self.variants(ntype).get((config or {}).get(key))

    @property
    def action_types(self) -> list[str]:
        return list(self.variants("action"))

    @property
    def trigger_types(self) -> list[str]:
        return list(self.variants("trigger"))

    def branching_types(self) -> list[str]:
        return [n["type"] for n in self.doc["nodes"] if n["handles"].get("else")]

    # -- configuration contract --------------------------------------------

    def required_groups(self, ntype: str, config: dict | None = None) -> list[list[str]]:
        """Alternative-key groups a configured node of this kind must satisfy.

        The node's own groups plus, where one config key selects a variant,
        that variant's groups. ``trigger`` requires ``type``; a ``schedule``
        trigger additionally requires ``cron``.
        """
        node = self.node(ntype)
        if node is None:
            return []
        groups = [list(g) for g in node["config"].get("required") or []]
        variant = self.variant(ntype, config)
        if variant is not None:
            groups += [list(g) for g in variant["config"].get("required") or []]
        return groups

    def defaults(self, ntype: str, config: dict | None = None) -> dict[str, Any]:
        node = self.node(ntype)
        if node is None:
            return {}
        out = dict(node["config"].get("defaults") or {})
        variant = self.variant(ntype, config)
        if variant is not None:
            out.update(variant["config"].get("defaults") or {})
        return out

    def missing(self, ntype: str, config: dict | None) -> list[str]:
        """Which required groups ``config`` leaves empty, as ``a|b|c`` strings."""
        cfg = config or {}
        return ["|".join(g) for g in self.required_groups(ntype, cfg)
                if not any(_present(cfg.get(k)) for k in g)]

    def step_errors(self, step: dict) -> list[str]:
        """Everything wrong with one Blueprint step against this catalog."""
        ntype = step.get("type")
        cfg = step.get("config") if isinstance(step.get("config"), dict) else {}
        node = self.node(ntype)
        if node is None:
            return [f"type {ntype!r} is not a catalog node "
                    f"(one of: {', '.join(self.node_types)})"]
        errors: list[str] = []
        key = self.variant_key(ntype)
        if key:
            chosen = cfg.get(key)
            if chosen is None:
                errors.append(f"config.{key} is required "
                              f"(one of: {', '.join(self.variants(ntype))})")
            elif chosen not in self.variants(ntype):
                errors.append(f"config.{key}={chosen!r} is not a catalog variant "
                              f"(one of: {', '.join(self.variants(ntype))})")
        for group in self.missing(ntype, cfg):
            if key and group == key:
                continue  # reported above with the choices
            errors.append(f"config needs one of: {group}")
        return errors

    def workflow_errors(self, body: dict) -> list[str]:
        """Everything wrong with one proposed Blueprint workflow: a trigger
        outside the catalog, a step that is not a catalog node, a node whose
        declared configuration is left empty. Each line names the step."""
        errors: list[str] = []
        trigger = body.get("trigger") or {}
        if isinstance(trigger, dict) and trigger.get("kind") not in self.trigger_types:
            errors.append(f"trigger.kind {trigger.get('kind')!r} is not a catalog trigger "
                          f"(one of: {', '.join(self.trigger_types)})")
        for step in body.get("steps") or []:
            if not isinstance(step, dict):
                continue
            errors.extend(f"{step.get('key') or '?'}: {e}" for e in self.step_errors(step))
        return errors

    # -- prompt rendering ---------------------------------------------------

    def digest(self, types: Iterable[str] | None = None) -> str:
        """A compact rendering for a prompt: what exists and what each needs.

        ``types`` narrows it to the nodes a task is actually using, so a
        follow-up that touches one workflow does not pay for the whole list.
        """
        wanted = set(types) if types is not None else None
        lines = ["`*` marks a required config key; `a|b` means one of them. "
                 "A step that leaves a required group empty is refused."]
        cats = {c["id"]: c["label"] for c in self.categories}
        for cat_id, cat_label in cats.items():
            entries = [n for n in self.doc["nodes"] if n["category"] == cat_id
                       and (wanted is None or n["type"] in wanted)]
            if not entries:
                continue
            lines.append(f"\n## {cat_label}")
            for n in entries:
                head = f"- {n['type']} — {n['description']}"
                if n["handles"].get("else"):
                    head += " (branches: first `next` is the then-branch, second is the else-branch)"
                if not n["handles"].get("out"):
                    head += " (terminal)"
                lines.append(head)
                own = self._sig(n["config"])
                if own:
                    lines.append(f"    config: {own}")
                vkey = n.get("variantKey")
                if vkey:
                    lines.append(f"    config.{vkey} chooses the variant:")
                    for v in n["variants"]:
                        sig = self._sig(v["config"])
                        lines.append(f"      {v['key']} — {v['description']}"
                                     + (f"; config: {sig}" if sig else ""))
        return "\n".join(lines)

    @staticmethod
    def _sig(config: dict) -> str:
        parts = ["*" + "|".join(g) for g in config.get("required") or []]
        parts += [f"{k}={json.dumps(v)}" for k, v in (config.get("defaults") or {}).items()]
        return ", ".join(parts)


@functools.lru_cache(maxsize=1)
def workflow_nodes(path: str | Path = WORKFLOW_NODE_CATALOG_PATH) -> WorkflowNodeCatalog:
    return WorkflowNodeCatalog(json.loads(Path(path).read_text("utf-8")))
