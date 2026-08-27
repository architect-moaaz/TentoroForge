"""Simulator dispatchers for the action types the registry was missing.

Ten of the fifteen action types the editor can author had no dispatcher at
all (register A8-1): ``db_insert``, ``db_update``, ``db_delete``,
``set_variable``, ``transform``, ``generate_document`` and the four
``ai_*`` actions. They fell through to :class:`CustomActionDispatcher`,
which logs a line and returns ``{"result": "success"}`` — so the in-editor
Simulator painted those nodes green while performing no work. That is the
tool an author uses to confirm an edit is correct, which makes a false
green a confidently wrong answer rather than a missing feature.

The Simulator does not execute side effects — ``DbQueryDispatcher`` has
always logged rather than queried, and the runtime that really writes rows
is the TypeScript engine shipped into the generated app. So these
dispatchers do three things instead:

1. **Resolve the config** through the same
   :class:`~runtime.variable_resolver.VariableResolver` the real
   dispatchers use, so an unresolvable binding surfaces HERE rather than
   at runtime.
2. **Return the SHIPPED handler's output shape**, key for key
   (``db_update`` → ``{updated: {count, rows}, count, rows}`` and so on),
   so a downstream node binding to ``{{n.output.updated.count}}`` reads a
   present value in simulation exactly as it will in production.
3. **Mark the result ``simulated: True``** and carry no fabricated
   success flag, so nothing downstream can mistake a simulated step for a
   performed one.

``set_variable`` and ``transform`` are pure computation, so they are
simulated by actually computing — there is nothing to fake.

Shapes are mirrored from ``backend/templates/runtime/workflows/index.ts``
(db_*, generate_document) and ``.../ai.ts`` (the ai_* family). The
conformance case in ``qa/pipeline/area8_simulator.py`` pins the two
vocabularies together so they cannot drift apart again — the same
two-catalogs-of-one-contract disease as the pluralizers and the FEEL
function tables.
"""

import logging
from typing import Any

from runtime.actions.base import ActionDispatcher

logger = logging.getLogger(__name__)


class _SimulatedDispatcher(ActionDispatcher):
    """Shared plumbing: resolve config, never execute, never claim success."""

    action_type: str = "simulated"

    def _resolved(self, config: dict, *keys: str) -> dict:
        """Resolve the named string keys, reporting failures instead of
        swallowing them — an unresolvable binding is exactly what the
        author ran the Simulator to find."""
        out: dict[str, Any] = {}
        for k in keys:
            raw = config.get(k)
            if isinstance(raw, str):
                try:
                    out[k] = self.resolver.resolve_string(raw)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "%s: could not resolve %s=%r: %s",
                        self.action_type, k, raw, exc,
                    )
                    out[k] = None
                    out.setdefault("unresolved", []).append(k)
            else:
                out[k] = raw
        return out

    def _resolve_map(self, raw: Any, what: str) -> dict:
        """Resolve a field→binding map (``values`` / ``where``). Isolated per
        entry so one bad binding does not discard the rest."""
        if not isinstance(raw, dict):
            return {}
        out: dict[str, Any] = {}
        for field, binding in raw.items():
            if isinstance(binding, str):
                try:
                    out[field] = self.resolver.resolve_string(binding)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "%s: could not resolve %s[%s]=%r: %s",
                        self.action_type, what, field, binding, exc,
                    )
                    out[field] = None
            else:
                out[field] = binding
        return out


# --------------------------------------------------------------------------- #
# Database actions — shapes from templates/runtime/workflows/index.ts
# --------------------------------------------------------------------------- #

class DbInsertDispatcher(_SimulatedDispatcher):
    """Shipped shape: ``{inserted: row|true}``."""

    action_type = "db_insert"

    async def execute(self, config: dict) -> dict:
        table = self._resolved(config, "table").get("table")
        values = self._resolve_map(config.get("values"), "values")
        if not table:
            return {"action_type": self.action_type, "simulated": True,
                    "error": "unknown table", "inserted": None}
        logger.info("simulated db_insert into %s with %d value(s)", table, len(values))
        return {
            "action_type": self.action_type,
            "simulated": True,
            "table": table,
            "values": values,
            # The shipped handler returns the inserted row; simulation knows
            # the values it WOULD write but not the DB-assigned columns.
            "inserted": values,
        }


class DbUpdateDispatcher(_SimulatedDispatcher):
    """Shipped shape: ``{updated: {count, rows}, updatedRows, count, rows}``."""

    action_type = "db_update"

    async def execute(self, config: dict) -> dict:
        table = self._resolved(config, "table").get("table")
        values = self._resolve_map(config.get("values"), "values")
        where = self._resolve_map(config.get("where"), "where")
        if not table:
            return {"action_type": self.action_type, "simulated": True,
                    "error": "unknown table",
                    "updated": {"count": 0, "rows": []}, "count": 0, "rows": []}
        if not where:
            # The runtime refuses this with "WHERE resolved to zero
            # conditions"; simulation must refuse it too rather than imply
            # the update would land.
            logger.warning(
                "simulated db_update on %s has no resolvable WHERE — the "
                "runtime would refuse this update", table,
            )
            return {"action_type": self.action_type, "simulated": True,
                    "table": table, "values": values,
                    "error": "WHERE resolved to zero conditions",
                    "updated": {"count": 0, "rows": []}, "count": 0, "rows": []}
        logger.info("simulated db_update on %s where %s", table, where)
        return {
            "action_type": self.action_type,
            "simulated": True,
            "table": table,
            "values": values,
            "where": where,
            # Row COUNT is unknowable without executing; the keys exist so
            # downstream bindings resolve, and `simulated` says why the
            # count is not authoritative.
            "updated": {"count": None, "rows": []},
            "updatedRows": [],
            "count": None,
            "rows": [],
        }


class DbDeleteDispatcher(_SimulatedDispatcher):
    """Shipped shape: ``{deleted: {count}, count}``."""

    action_type = "db_delete"

    async def execute(self, config: dict) -> dict:
        table = self._resolved(config, "table").get("table")
        where = self._resolve_map(config.get("where"), "where")
        if not table:
            return {"action_type": self.action_type, "simulated": True,
                    "error": "unknown table", "deleted": {"count": 0}, "count": 0}
        if not where:
            logger.warning(
                "simulated db_delete on %s has no resolvable WHERE — the "
                "runtime would refuse rather than delete every row", table,
            )
            return {"action_type": self.action_type, "simulated": True,
                    "table": table,
                    "error": "WHERE resolved to zero conditions",
                    "deleted": {"count": 0}, "count": 0}
        logger.info("simulated db_delete from %s where %s", table, where)
        return {
            "action_type": self.action_type,
            "simulated": True,
            "table": table,
            "where": where,
            "deleted": {"count": None},
            "count": None,
        }


# --------------------------------------------------------------------------- #
# Pure computation — simulated by actually computing
# --------------------------------------------------------------------------- #

class SetVariableDispatcher(_SimulatedDispatcher):
    """Shipped shape: ``{[variableName]: value, value}`` (engine.ts, inline)."""

    action_type = "set_variable"

    async def execute(self, config: dict) -> dict:
        name = config.get("variableName") or config.get("name")
        raw = config.get("expression", config.get("value"))
        value = raw
        if isinstance(raw, str):
            try:
                value = self.resolver.resolve_string(raw)
            except Exception as exc:  # noqa: BLE001
                logger.warning("set_variable: could not resolve %r: %s", raw, exc)
                value = None
        if not name:
            # The engine ignores a set_variable with no variableName; say so
            # rather than reporting a value nobody can read.
            return {"action_type": self.action_type, "simulated": True,
                    "error": "set_variable has no variableName", "value": None}
        return {
            "action_type": self.action_type,
            "simulated": True,
            name: value,
            "value": value,
        }


class TransformDispatcher(_SimulatedDispatcher):
    """Shipped shape: ``{value}`` (engine.ts, inline)."""

    action_type = "transform"

    async def execute(self, config: dict) -> dict:
        raw = config.get("expression", config.get("value"))
        value = raw
        if isinstance(raw, str):
            try:
                value = self.resolver.resolve_string(raw)
            except Exception as exc:  # noqa: BLE001
                logger.warning("transform: could not resolve %r: %s", raw, exc)
                value = None
        return {"action_type": self.action_type, "simulated": True, "value": value}


# --------------------------------------------------------------------------- #
# Document + AI — real execution belongs to the shipped runtime
# --------------------------------------------------------------------------- #

class GenerateDocumentDispatcher(_SimulatedDispatcher):
    """Shipped shape: ``{generated, url, fileId}``."""

    action_type = "generate_document"

    async def execute(self, config: dict) -> dict:
        meta = self._resolved(config, "title", "template", "record")
        return {
            "action_type": self.action_type,
            "simulated": True,
            # NOT `generated: True` — no document exists. The keys are
            # present so bindings resolve; their emptiness is the truth.
            "generated": False,
            "url": None,
            "fileId": None,
            "reason": "document rendering runs in the shipped app, not the Simulator",
            **meta,
        }


class _AiDispatcher(_SimulatedDispatcher):
    """Common base: an AI call has no deterministic simulated answer."""

    async def _base(self, config: dict) -> dict:
        meta = self._resolved(config, "prompt", "model", "instructions")
        return {
            "action_type": self.action_type,
            "simulated": True,
            "reason": "model inference runs in the shipped app, not the Simulator",
            **meta,
        }


class AiGenerateDispatcher(_AiDispatcher):
    """Shipped shape: ``{text, generated_text, generated, tone, output}``."""

    action_type = "ai_generate"

    async def execute(self, config: dict) -> dict:
        base = await self._base(config)
        return {**base, "text": None, "generated_text": None,
                "generated": None, "tone": config.get("tone"), "output": None}


class AiClassifyDispatcher(_AiDispatcher):
    """Shipped shape: ``{label, classification, confidence,
    meets_threshold, output}``."""

    action_type = "ai_classify"

    async def execute(self, config: dict) -> dict:
        base = await self._base(config)
        return {**base, "label": None, "classification": None,
                "confidence": None, "meets_threshold": None, "output": None}


class AiExtractDispatcher(_AiDispatcher):
    """Shipped shape: ``{data, extracted_fields, extracted, output}``."""

    action_type = "ai_extract"

    async def execute(self, config: dict) -> dict:
        base = await self._base(config)
        return {**base, "data": None, "extracted_fields": None,
                "extracted": None, "output": None}


class AiDecideDispatcher(_AiDispatcher):
    """Shipped shape: ``{decision, option, confidence, reasoning,
    rationale, output}``."""

    action_type = "ai_decide"

    async def execute(self, config: dict) -> dict:
        base = await self._base(config)
        return {**base, "decision": None, "option": None, "confidence": None,
                "reasoning": None, "rationale": None, "output": None}
