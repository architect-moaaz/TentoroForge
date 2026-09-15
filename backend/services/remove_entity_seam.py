"""Remove an entity — the removal sibling of :mod:`services.add_entity_seam`.

The highest-blast-radius data-model change: dropping the table takes its data,
and everything that named it — a workflow that reads or writes it, a page whose
primary entity it is, a foreign key on another entity, a relationship — is
orphaned. This seam does the three-file surgery add_entity's inverse implies:

    * ``contracts/resource-registry.json`` — the entity removed
    * ``src/db/schema/<slug>.ts``          — the Drizzle module deleted
    * ``src/db/schema/index.ts``           — its barrel export line removed

It does NOT chase the cascade. The completeness checks already do: an orphaned
page's Page↔Workflow / functional finding, a dangling relationship's
API↔Database finding, a workflow that mutates a now-unknown entity's Workflow↔API
finding. So the caller confirms first (the blast radius is real and shown), the
delete lands, and the loop surfaces what to repair. Auth-managed entities
(users / a credential table) are refused — next-auth owns them and dropping one
breaks sign-in.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from services.atomic_apply import BundleOp


class RemoveEntityError(ValueError):
    """Raised when the seam cannot build a bundle. Caller renders the message."""

_AUTH_NAMES = {"user", "users", "account", "accounts", "session", "sessions"}
_CRED_COLS = {"password", "passwordhash", "password_hash", "hashedpassword", "hashed_password"}


def _is_auth_entity(entity: dict) -> bool:
    if str(entity.get("name") or "").lower() in _AUTH_NAMES \
            or str(entity.get("table") or "").lower() in _AUTH_NAMES:
        return True
    return any(str((f or {}).get("name") or "").lower().replace("_", "") in
               {c.replace("_", "") for c in _CRED_COLS}
               for f in entity.get("fields") or [])


def dependents(doc_or_registry: dict, entity_name: str) -> list[str]:
    """Human-readable cascade for the confirmation summary — the pages,
    workflows and relationships that name this entity. Best-effort: reads a
    Blueprint doc when given one, and always the registry it can see."""
    out: list[str] = []
    name = entity_name.strip().lower()
    ids = {str(e.get("id")) for e in (doc_or_registry.get("data") or {}).get("entities") or []
           if str(e.get("name") or "").lower() == name}
    ids |= {name}
    for p in doc_or_registry.get("pages") or []:
        pe = str((p.get("data") or {}).get("primaryEntity") or "").lower()
        if pe in ids:
            out.append(f"page {p.get('route') or p.get('id')} (its primary entity)")
    for w in doc_or_registry.get("workflows") or []:
        for i in w.get("inputs") or []:
            if str(i.get("entity") or "").lower() in ids:
                out.append(f"workflow {w.get('name') or w.get('id')} (operates on it)")
                break
    for rel in (doc_or_registry.get("data") or {}).get("relationships") or []:
        if str(rel.get("from") or "").lower() in ids or str(rel.get("to") or "").lower() in ids:
            out.append(f"relationship {rel.get('from')}→{rel.get('to')}")
    return out


def build_remove_entity_bundle(output_dir: str, *, entity: str) -> list[BundleOp]:
    """Compose the atomic bundle that drops one entity's table, module and
    barrel export."""
    entity = str(entity or "").strip()
    if not entity:
        raise RemoveEntityError("entity is required")

    out = Path(output_dir)
    reg_path = out / "contracts" / "resource-registry.json"
    if not reg_path.is_file():
        raise RemoveEntityError("registry not found: contracts/resource-registry.json")
    try:
        registry = json.loads(reg_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise RemoveEntityError(f"registry unreadable: {e}") from e
    entities = registry.get("entities")
    if not isinstance(entities, list):
        raise RemoveEntityError("registry.entities must be a list")

    target = next((e for e in entities
                   if isinstance(e, dict) and str(e.get("name") or "").lower() == entity.lower()),
                  None)
    if target is None:
        known = ", ".join(str(e.get("name")) for e in entities if isinstance(e, dict)) or "(none)"
        raise RemoveEntityError(f"entity {entity!r} not found in the registry — known: {known}")
    if _is_auth_entity(target):
        raise RemoveEntityError(
            f"{target.get('name')!r} is an auth-managed entity (users / credential store) — "
            f"next-auth owns it and dropping it breaks sign-in.")

    slug = str(target.get("slug") or "").strip() or _to_kebab(str(target.get("name") or entity))
    registry["entities"] = [e for e in entities if e is not target]

    ops = [
        BundleOp(path="contracts/resource-registry.json",
                 content=json.dumps(registry, indent=2) + "\n", kind="registry"),
        BundleOp(path=f"src/db/schema/{slug}.ts", content="", kind="delete"),
    ]

    # Remove the barrel export line for this module, if the barrel is present.
    barrel_path = out / "src" / "db" / "schema" / "index.ts"
    if barrel_path.is_file():
        barrel = barrel_path.read_text(encoding="utf-8")
        kept = [ln for ln in barrel.splitlines(keepends=True)
                if f'"./{slug}"' not in ln and f"'./{slug}'" not in ln]
        new_barrel = "".join(kept)
        if new_barrel != barrel:
            ops.append(BundleOp(path="src/db/schema/index.ts",
                                content=new_barrel, kind="barrel"))

    return ops


def _to_kebab(name: str) -> str:
    s = re.sub(r"(?<!^)(?=[A-Z])", "-", name).lower()
    return re.sub(r"[^a-z0-9-]+", "-", s).strip("-")
