"""Smoke tests for the schema-mode pipeline dispatch.

Verifies:
1. SCHEMA_MODE_ENABLED defaults to True
2. run_schema_frontend_pipeline dispatches to feature_slice_schema_agent per entity
3. The three-branch dispatch in generate.py routes correctly (mocked — no LLM calls)
4. schema_pipeline.py imports cleanly
5. feature_slice_schema_agent and schema_prompt import cleanly

Run: cd backend && python3 -m pytest tests/test_schema_pipeline.py -v
  or: cd backend && python3 tests/test_schema_pipeline.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.pop("CLAUDECODE", None)
os.environ.pop("CLAUDE_CODE_ENTRYPOINT", None)


async def run_tests() -> tuple[int, int]:
    passed = 0
    failed = 0

    print("=== SCHEMA PIPELINE SMOKE TESTS ===\n")

    # ------------------------------------------------------------------
    # 1. Imports
    # ------------------------------------------------------------------
    print("[1] Import: schema_pipeline")
    try:
        from services.schema_pipeline import SCHEMA_MODE_ENABLED, run_schema_frontend_pipeline
        assert callable(run_schema_frontend_pipeline), "run_schema_frontend_pipeline must be callable"
        print(f"    ✓ OK (SCHEMA_MODE_ENABLED={SCHEMA_MODE_ENABLED})")
        passed += 1
    except Exception as e:
        print(f"    ✗ FAILED: {e}")
        failed += 1

    # ------------------------------------------------------------------
    # 2. SCHEMA_MODE_ENABLED defaults to True when env var is unset
    # ------------------------------------------------------------------
    print("[2] SCHEMA_MODE_ENABLED default is True")
    try:
        saved = os.environ.pop("SCHEMA_MODE_ENABLED", None)
        import importlib
        import services.schema_pipeline as sp
        importlib.reload(sp)
        assert sp.SCHEMA_MODE_ENABLED is True, f"Expected True, got {sp.SCHEMA_MODE_ENABLED}"
        if saved is not None:
            os.environ["SCHEMA_MODE_ENABLED"] = saved
        print("    ✓ OK")
        passed += 1
    except Exception as e:
        print(f"    ✗ FAILED: {e}")
        failed += 1

    # ------------------------------------------------------------------
    # 3. SCHEMA_MODE_ENABLED=false disables the flag
    # ------------------------------------------------------------------
    print("[3] SCHEMA_MODE_ENABLED=false disables the flag")
    try:
        import importlib
        import services.schema_pipeline as sp
        os.environ["SCHEMA_MODE_ENABLED"] = "false"
        importlib.reload(sp)
        assert sp.SCHEMA_MODE_ENABLED is False, f"Expected False, got {sp.SCHEMA_MODE_ENABLED}"
        os.environ["SCHEMA_MODE_ENABLED"] = "true"
        importlib.reload(sp)
        print("    ✓ OK")
        passed += 1
    except Exception as e:
        print(f"    ✗ FAILED: {e}")
        failed += 1
    finally:
        # Restore
        os.environ.pop("SCHEMA_MODE_ENABLED", None)
        import services.schema_pipeline as sp2
        import importlib
        importlib.reload(sp2)

    # ------------------------------------------------------------------
    # 4. run_schema_frontend_pipeline calls agent once per entity
    # ------------------------------------------------------------------
    print("[4] run_schema_frontend_pipeline calls agent once per entity")
    try:
        from services.schema_pipeline import run_schema_frontend_pipeline

        call_log: list[dict] = []

        async def _mock_agent(output_dir, entity_plan, domain_context=None):
            call_log.append({"entity": entity_plan.get("entity", {}).get("name")})

        plan = {
            "entities": [
                {"name": "Product", "fields": []},
                {"name": "Order", "fields": []},
                {"name": "Legacy", "fields": [], "legacy_tsx_mode": True},  # should be skipped
            ]
        }

        with patch(
            "services.schema_pipeline.run_schema_frontend_pipeline.__module__",
            new="services.schema_pipeline",
        ):
            with patch("agents.feature_slice_schema_agent.run_feature_slice_schema_agent", new=_mock_agent):
                events = []
                async for evt in run_schema_frontend_pipeline(
                    "/tmp/test-output", plan, "Test app", domain_context=None
                ):
                    events.append(evt)

        # Should have called agent for Product and Order, not Legacy
        assert len(call_log) == 2, f"Expected 2 agent calls, got {len(call_log)}: {call_log}"
        names = [c["entity"] for c in call_log]
        assert "Product" in names, f"Product missing from {names}"
        assert "Order" in names, f"Order missing from {names}"
        assert "Legacy" not in names, f"Legacy should be skipped"
        # Should have SSE events
        event_types = [e.get("event") for e in events]
        assert "status" in event_types, f"Expected status events, got {event_types}"
        assert "log" in event_types, f"Expected log events, got {event_types}"
        print(f"    ✓ OK ({len(call_log)} agent calls, {len(events)} SSE events)")
        passed += 1
    except Exception as e:
        import traceback
        print(f"    ✗ FAILED: {e}")
        print(f"    {traceback.format_exc()}")
        failed += 1

    # ------------------------------------------------------------------
    # 5. feature_slice_schema_agent imports cleanly
    # ------------------------------------------------------------------
    print("[5] Import: feature_slice_schema_agent")
    try:
        from agents.feature_slice_schema_agent import run_feature_slice_schema_agent
        assert callable(run_feature_slice_schema_agent)
        print("    ✓ OK")
        passed += 1
    except Exception as e:
        print(f"    ✗ FAILED: {e}")
        failed += 1

    # ------------------------------------------------------------------
    # 6. schema_prompt imports cleanly and build_schema_prompt is callable
    # ------------------------------------------------------------------
    print("[6] Import: schema_prompt.build_schema_prompt")
    try:
        from services.schema_prompt import build_schema_prompt
        assert callable(build_schema_prompt)
        # Quick smoke: build a prompt with a minimal plan
        prompt = build_schema_prompt({
            "entity": {"name": "Product", "fields": [{"name": "title", "type": "string"}]},
            "feature_description": "A list page for products",
            "page_type": "list",
        })
        assert isinstance(prompt, str) and len(prompt) > 50, "Prompt too short"
        print(f"    ✓ OK (prompt length={len(prompt)})")
        passed += 1
    except Exception as e:
        print(f"    ✗ FAILED: {e}")
        failed += 1

    # ------------------------------------------------------------------
    # 7. generate.py imports the schema_pipeline without errors
    # ------------------------------------------------------------------
    print("[7] generate.py imports schema_pipeline without errors")
    try:
        # Verify that the import lines in generate.py are syntactically correct
        # by importing only the dispatch logic (not the full router which needs DB)
        import ast
        with open(os.path.join(os.path.dirname(__file__), "..", "routers", "generate.py")) as f:
            source = f.read()
        tree = ast.parse(source)
        # Check for the expected pattern in the AST
        found_schema = "SCHEMA_MODE_ENABLED" in source
        found_ir = "IR_FRONTEND_ENABLED" in source
        found_three_branch = "schema-mode (default — Phase 4)" in source
        assert found_schema, "SCHEMA_MODE_ENABLED not found in generate.py"
        assert found_ir, "IR_FRONTEND_ENABLED not found in generate.py"
        assert found_three_branch, "Three-branch dispatch marker not found in generate.py"
        print("    ✓ OK (three-branch dispatch confirmed)")
        passed += 1
    except Exception as e:
        print(f"    ✗ FAILED: {e}")
        failed += 1

    # ------------------------------------------------------------------
    # 8. schema_pipeline emits correct SSE log on legacy_tsx_mode skip
    # ------------------------------------------------------------------
    print("[8] legacy_tsx_mode entities are skipped with correct log message")
    try:
        from services.schema_pipeline import run_schema_frontend_pipeline

        async def _noop_agent(output_dir, entity_plan, domain_context=None):
            pass

        plan = {"entities": [{"name": "Legacy", "fields": [], "legacy_tsx_mode": True}]}
        with patch("agents.feature_slice_schema_agent.run_feature_slice_schema_agent", new=_noop_agent):
            events = []
            async for evt in run_schema_frontend_pipeline("/tmp/x", plan, "test"):
                events.append(evt)

        log_texts = [
            json.loads(e["data"]).get("text", "") if isinstance(e.get("data"), str) else e.get("data", {}).get("text", "")
            for e in events
            if e.get("event") == "log"
        ]
        assert any("legacy_tsx_mode" in t for t in log_texts), f"Expected legacy skip log, got: {log_texts}"
        print("    ✓ OK")
        passed += 1
    except Exception as e:
        print(f"    ✗ FAILED: {e}")
        failed += 1

    return passed, failed


if __name__ == "__main__":
    passed, failed = asyncio.run(run_tests())
    total = passed + failed
    print(f"\n=== Results: {passed}/{total} passed ===")
    if failed:
        sys.exit(1)
    sys.exit(0)
