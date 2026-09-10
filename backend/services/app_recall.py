"""App Recall — the per-app *generation dossier*.

The context engine today only forward-injects static contracts into the
generators; there is no history recall. This module gives a later fix-chat the
missing half: *why* an app is the way it is — its original prompt, its
finalized plan, its entities/roles/relationships, the contracts that were
emitted, and the recent change history — so diagnosis can reason against
intent, not just against the current files.

Two entry points:

* :func:`emit_generation_dossier` — a pure file write, called once at
  generation time. It snapshots ``{prompt, plan, generatedAt}`` to
  ``contracts/generation-dossier.json`` so recall works with NO database.
* :func:`assemble_recall` — reads the on-disk dossier + the resource registry
  + the other contracts, and (when a DB session is supplied) OVERLAYS the live
  plan / original prompt from Postgres. Live wins over the on-disk snapshot.

No wall-clock is read here (no ``datetime.now``): timestamps are passed in by
the caller, keeping the library deterministic and testable.
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_CONTRACTS_DIR = "contracts"
_DOSSIER_NAME = "generation-dossier.json"
_REGISTRY_NAME = "resource-registry.json"

# how many recent change instructions / git subjects to recall
_HISTORY_LIMIT = 8
# cap columns rendered per entity in the compact prompt block
_COLS_PER_ENTITY = 6


# ---------------------------------------------------------------------------
# emit — the on-disk snapshot (pure write, DB-free recall)
# ---------------------------------------------------------------------------

def emit_generation_dossier(
    output_dir: str,
    plan: dict,
    prompt: Optional[str] = None,
    generated_at: Optional[str] = None,
) -> str:
    """Write ``contracts/generation-dossier.json`` and return its path.

    The dossier is ``{prompt, plan, generatedAt}``. ``generatedAt`` is whatever
    timestamp string the caller passes (or ``null`` — this function never reads
    the clock). Creates the ``contracts`` directory if needed. Pure file write.
    """
    contracts = Path(output_dir) / _CONTRACTS_DIR
    contracts.mkdir(parents=True, exist_ok=True)
    path = contracts / _DOSSIER_NAME
    dossier = {
        "prompt": prompt,
        "plan": plan,
        "generatedAt": generated_at,
    }
    path.write_text(json.dumps(dossier, indent=2), encoding="utf-8")
    return str(path)


# ---------------------------------------------------------------------------
# RecallContext
# ---------------------------------------------------------------------------

@dataclass
class RecallContext:
    """Everything the fix-assistant needs to diagnose an app against intent."""

    prompt: Optional[str] = None
    plan: Optional[dict] = None
    entities: list[dict] = field(default_factory=list)
    roles: list[Any] = field(default_factory=list)
    relationships: list[Any] = field(default_factory=list)
    interactions: list[Any] = field(default_factory=list)
    contracts: dict = field(default_factory=dict)
    history: list[dict] = field(default_factory=list)

    # Set by :func:`assemble_recall`; used by :meth:`to_prompt_block` to
    # prepend the app-map skeleton so Smith opens every turn already
    # knowing the app's shape. Optional so tests that construct a bare
    # ``RecallContext()`` still work.
    output_dir: Optional[str] = None

    # -- rendering ---------------------------------------------------------
    def is_empty(self) -> bool:
        return not (self.prompt or self.plan or self.entities)

    def _app_map_prefix(self) -> str:
        """Return the app-map skeleton block, or empty string if there's
        no output_dir on this RecallContext (backward-compat)."""
        if not self.output_dir:
            return ""
        try:
            from services.app_map import get_app_map
            from services.app_map_render import render_app_map_skeleton
            return render_app_map_skeleton(get_app_map(self.output_dir))
        except Exception:  # noqa: BLE001 — never fail a turn on the map
            return ""

    def to_prompt_block(self) -> str:
        """Compact, token-efficient rendering for a diagnosis prompt.

        No raw JSON dumps — a few tight lines the model can read at a glance.
        Prepends the app-map skeleton (from :mod:`services.app_map`) so
        Smith reads the shape of the app FIRST on every turn.
        """
        prefix = self._app_map_prefix()
        if self.is_empty():
            body = "No generation recall available for this app."
            return f"{prefix}\n\n{body}" if prefix else body

        lines: list[str] = []

        intent = self.prompt or (self.plan or {}).get("description") or "unknown"
        lines.append(f"APP INTENT: {_clip(intent, 400)}")

        if self.entities:
            ents = []
            for e in self.entities:
                cols = [c.get("name") for c in e.get("columns", []) if c.get("name")]
                shown = ", ".join(cols[:_COLS_PER_ENTITY])
                if len(cols) > _COLS_PER_ENTITY:
                    shown += ", …"
                name = e.get("name") or e.get("slug") or "?"
                ents.append(f"{name}({shown})" if shown else str(name))
            lines.append("ENTITIES: " + "; ".join(ents))

        roles = _role_names(self.roles)
        lines.append("ROLES: " + (", ".join(roles) if roles else "none declared"))

        wf = _workflow_lines(self.interactions, self.plan)
        if wf:
            lines.append("KEY WORKFLOWS/INTERACTIONS: " + "; ".join(wf))

        if self.relationships:
            rels = []
            for r in self.relationships[:_HISTORY_LIMIT]:
                if isinstance(r, dict):
                    frm = r.get("from") or r.get("from_entity")
                    to = r.get("to") or r.get("to_entity")
                    col = r.get("fkColumn")
                    rels.append(f"{frm}.{col}→{to}" if col else f"{frm}→{to}")
            if rels:
                lines.append("RELATIONSHIPS: " + "; ".join(rels))

        if self.history:
            texts = [h.get("text", "") for h in self.history if h.get("text")]
            if texts:
                lines.append("RECENT CHANGES: " + " | ".join(_clip(t, 120) for t in texts[:_HISTORY_LIMIT]))

        body = "\n".join(lines)
        return f"{prefix}\n\n{body}" if prefix else body


# ---------------------------------------------------------------------------
# assemble — read on-disk snapshot + registry, overlay live DB
# ---------------------------------------------------------------------------

def assemble_recall(
    output_dir: str,
    project_id: Any = None,
    db_session: Any = None,
) -> RecallContext:
    """Assemble a :class:`RecallContext` for one app.

    On-disk first (works without a database): the generation-dossier snapshot
    plus the resource registry and contract summaries. When ``db_session`` +
    ``project_id`` are supplied, the *live* plan and original prompt from
    Postgres OVERLAY the snapshot (live wins).
    """
    out = Path(output_dir)
    ctx = RecallContext(output_dir=str(out))

    # 1. on-disk dossier snapshot -----------------------------------------
    dossier = _read_json(out / _CONTRACTS_DIR / _DOSSIER_NAME) or {}
    ctx.prompt = dossier.get("prompt")
    ctx.plan = dossier.get("plan")

    # 2. live DB overlay (live wins) --------------------------------------
    if db_session is not None and project_id is not None:
        live_plan, live_prompt = _live_plan_and_prompt(db_session, project_id)
        if live_plan is not None:
            ctx.plan = live_plan
        if live_prompt:
            ctx.prompt = live_prompt

    # 3. resource registry -------------------------------------------------
    registry = _read_json(out / _CONTRACTS_DIR / _REGISTRY_NAME) or {}
    ctx.entities = _entity_summaries(registry.get("entities"))
    ctx.roles = registry.get("roles") or []
    ctx.relationships = registry.get("relationships") or []
    ctx.interactions = registry.get("interactions") or []

    # 4. contract summaries -----------------------------------------------
    ctx.contracts = _contract_summary(out / _CONTRACTS_DIR)

    # 5. change history ----------------------------------------------------
    ctx.history = _assemble_history(output_dir, project_id, db_session)

    return ctx


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _read_json(path: Path) -> Optional[Any]:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("app_recall: could not read %s: %s", path, exc)
    return None


def _entity_summaries(entities: Any) -> list[dict]:
    """Compact per-entity summary from the registry's ``entities`` map."""
    out: list[dict] = []
    if not isinstance(entities, dict):
        return out
    for key, spec in entities.items():
        if not isinstance(spec, dict):
            continue
        cols = []
        for c in spec.get("columns", []) or []:
            if isinstance(c, dict) and c.get("name"):
                cols.append({
                    "name": c.get("name"),
                    "type": c.get("type"),
                    "fk": c.get("fk"),
                    "notNull": c.get("notNull"),
                })
        out.append({
            "name": spec.get("name") or key,
            "slug": spec.get("slug"),
            "table": spec.get("table"),
            "columns": cols,
        })
    return out


def _contract_summary(contracts_dir: Path) -> dict:
    """Presence + counts for the key contracts (no raw dumps)."""
    fk = _read_json(contracts_dir / "fk-semantics.json")
    action = _read_json(contracts_dir / "action-contract.json")
    binding = _read_json(contracts_dir / "binding-contract.json")
    data = _read_json(contracts_dir / "data-contract.json")

    def _len(obj, key=None):
        try:
            target = obj.get(key) if (key and isinstance(obj, dict)) else obj
            return len(target)
        except Exception:
            return 0

    return {
        "fkSemantics": {"present": fk is not None, "entities": _len(fk)},
        "actionContract": {"present": action is not None, "actions": _len(action, "actions")},
        "bindingContract": {"present": binding is not None, "entities": _len(binding)},
        "dataContract": {"present": data is not None, "nodes": _len(data, "nodes")},
    }


def _live_plan_and_prompt(db_session: Any, project_id: Any) -> tuple[Optional[dict], Optional[str]]:
    """Best-effort read of the live plan + original prompt from Postgres.

    Uses a synchronous ``Session.query`` interface. Any failure (e.g. an async
    session that has no ``.query``) degrades to ``(None, None)`` so recall
    silently falls back to the on-disk snapshot.
    """
    try:
        from models.project import Conversation
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("app_recall: Conversation model unavailable: %s", exc)
        return None, None

    try:
        rows = (
            db_session.query(Conversation)
            .filter(Conversation.project_id == project_id)
            .order_by(Conversation.created_at.desc())
            .all()
        )
    except Exception as exc:
        logger.debug("app_recall: live conversation query failed: %s", exc)
        return None, None

    plan: Optional[dict] = None
    user_turns: list[Any] = []
    for c in rows or []:
        role_val = _role_value(getattr(c, "role", None))
        md = getattr(c, "metadata_", None)
        if plan is None and role_val == "assistant" and isinstance(md, dict) and md.get("plan"):
            plan = md.get("plan")
        if role_val == "user":
            user_turns.append(c)

    prompt: Optional[str] = None
    if user_turns:
        dated = [c for c in user_turns if getattr(c, "created_at", None) is not None]
        chosen = min(dated, key=lambda c: c.created_at) if dated else user_turns[0]
        prompt = getattr(chosen, "content", None)

    return plan, prompt


def _assemble_history(output_dir: str, project_id: Any, db_session: Any) -> list[dict]:
    """Recent change instructions: AgentJob.instruction (DB) + git subjects."""
    history: list[dict] = []

    # AgentJob instructions (only when a DB session is available)
    if db_session is not None and project_id is not None:
        try:
            from models.project import AgentJob
            rows = (
                db_session.query(AgentJob)
                .filter(AgentJob.project_id == project_id)
                .order_by(AgentJob.created_at.desc())
                .all()
            )
            for j in (rows or [])[:_HISTORY_LIMIT]:
                instr = getattr(j, "instruction", None)
                if instr:
                    history.append({"source": "agent_job", "text": str(instr)})
        except Exception as exc:
            logger.debug("app_recall: agent_job history skipped: %s", exc)

    # git log subjects (best-effort; skip if not a repo)
    for subject in _git_subjects(output_dir, _HISTORY_LIMIT):
        history.append({"source": "git", "text": subject})

    return history


def _git_subjects(output_dir: str, limit: int) -> list[str]:
    try:
        proc = subprocess.run(
            ["git", "-C", output_dir, "log", f"-{limit}", "--pretty=%s"],
            capture_output=True, text=True, timeout=5,
        )
        if proc.returncode != 0:
            return []
        return [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("app_recall: git log skipped for %s: %s", output_dir, exc)
        return []


def _role_value(role: Any) -> Optional[str]:
    if role is None:
        return None
    return str(getattr(role, "value", role))


def _role_names(roles: Any) -> list[str]:
    names: list[str] = []
    for r in roles or []:
        if isinstance(r, str):
            names.append(r)
        elif isinstance(r, dict):
            n = r.get("name") or r.get("id") or r.get("role")
            if n:
                names.append(str(n))
    return names


def _workflow_lines(interactions: Any, plan: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for it in interactions or []:
        if not isinstance(it, dict):
            continue
        label = it.get("label") or it.get("id")
        wf = it.get("workflowId")
        if not (label or wf):
            continue
        line = f"{label} → {wf}" if wf else str(label)
        page = it.get("sourcePage")
        if page:
            line += f" ({page})"
        if line not in seen:
            seen.add(line)
            out.append(line)
    if not out and isinstance(plan, dict):
        for wf in plan.get("workflows", []) or []:
            if isinstance(wf, dict):
                name = wf.get("id") or wf.get("name")
                if name and name not in seen:
                    seen.add(name)
                    out.append(str(name))
    return out[:_HISTORY_LIMIT]


def _clip(text: Any, limit: int) -> str:
    s = str(text)
    return s if len(s) <= limit else s[: limit - 1] + "…"
