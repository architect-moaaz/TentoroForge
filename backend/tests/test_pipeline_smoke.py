"""Smoke test for the full Figma → IR pipeline.

Run: python3 tests/test_pipeline_smoke.py
No LLM calls — tests every stage that previously crashed.
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.pop("CLAUDECODE", None)
os.environ.pop("CLAUDE_CODE_ENTRYPOINT", None)


async def run_tests():
    passed = 0
    failed = 0
    total = 7

    print("=== DESIGN2UI PIPELINE SMOKE TEST ===\n")

    # 1. DB
    print("[1/7] Database connection...")
    try:
        from database import async_session
        from sqlalchemy import text
        async with async_session() as session:
            await session.execute(text("SELECT 1"))
        print("  ✓ OK")
        passed += 1
    except Exception as e:
        print(f"  ✗ FAILED: {e}")
        failed += 1

    # 2. Figma URL parsing
    print("[2/7] Figma URL parsing...")
    try:
        from figma_parser import parse_figma_url
        p = parse_figma_url("https://www.figma.com/design/ABC123/Test?node-id=0-1")
        assert p["file_key"] == "ABC123"
        assert p["node_id"] == "0:1"
        print("  ✓ OK")
        passed += 1
    except Exception as e:
        print(f"  ✗ FAILED: {e}")
        failed += 1

    # 3. Plan JSON repair
    print("[3/7] Plan JSON extraction + repair...")
    try:
        from routers.generate import _extract_plan_json

        broken_cases = [
            # Extra quote after boolean
            '```plan-json\n{"m": "t", "f": [{"x": false"}]}\n```',
            # Trailing comma
            '```plan-json\n{"m": "t", "f": [1, 2, ]}\n```',
        ]
        for case in broken_cases:
            result = _extract_plan_json(case)
            assert result is not None, f"Failed to parse: {case}"
        print("  ✓ OK (2 repair patterns)")
        passed += 1
    except Exception as e:
        print(f"  ✗ FAILED: {e}")
        failed += 1

    # 4. Registry with flexible formats
    print("[4/7] Registry creation (flexible formats)...")
    try:
        from services.registry import create_registry

        plan = {
            "data_models": [{"name": "User", "fields": [{"name": "id", "type": "serial"}]}],
            "pages": [{"route": "/", "name": "Home", "description": "Home"}],
            "api_routes": [{"method": "GET", "path": "/api/users", "description": "List"}],
            "components": [
                {"name": "A", "props": ["p1", "p2"]},          # list of strings
                {"name": "B", "props": {"x": "string"}},       # dict
                {"name": "C"},                                   # no props
            ],
            "workflows": [
                {"name": "W1", "steps": ["s1", "s2"]},         # string steps
                {"name": "W2", "steps": [{"name": "s3"}]},     # dict steps
            ],
        }
        reg = create_registry(plan)
        assert len(reg["components"]) == 3
        assert len(reg["workflow_bindings"]) == 3  # s1, s2, s3
        print("  ✓ OK (list props, string steps, dict steps)")
        passed += 1
    except Exception as e:
        print(f"  ✗ FAILED: {e}")
        failed += 1

    # 5. IR adapter + compiler
    print("[5/7] IR adapter + compiler...")
    try:
        from services.ir_adapter import plan_to_app_spec
        from services.ir_compiler import generate_and_compile

        plan = {
            "module_name": "TestApp",
            "data_models": [
                {"name": "Task", "fields": [
                    {"name": "id", "type": "serial", "primaryKey": True},
                    {"name": "title", "type": "varchar(255)"},
                    {"name": "done", "type": "boolean"},
                ]},
            ],
            "pages": [{"route": "/tasks", "name": "Tasks"}],
            "api_routes": [{"method": "GET", "path": "/api/tasks"}],
        }
        spec = plan_to_app_spec(plan, "TestApp")
        result = await generate_and_compile(spec)
        assert len(result["files"]) > 0
        assert not result.get("errors")
        print(f"  ✓ OK ({len(result['ir']['pages'])} pages, {len(result['files'])} files)")
        passed += 1
    except Exception as e:
        print(f"  ✗ FAILED: {e}")
        failed += 1

    # 6. ResultMessage handling in ir_figma_pipeline
    print("[6/7] IR Figma pipeline message handling...")
    try:
        import importlib
        mod = importlib.import_module("services.ir_figma_pipeline")
        source = open(mod.__file__).read()
        # Verify the fix: AssistantMessage has .content, ResultMessage is skipped
        assert "isinstance(message, AssistantMessage)" in source
        assert "isinstance(message, ResultMessage)" in source
        assert "ResultMessage" in source
        # Make sure we don't access .content on ResultMessage
        lines = source.split("\n")
        for i, line in enumerate(lines):
            if "ResultMessage" in line and ".content" in line and "isinstance" not in line:
                raise AssertionError(f"Line {i+1} accesses .content on ResultMessage")
        print("  ✓ OK (ResultMessage skipped, no .content access)")
        passed += 1
    except Exception as e:
        print(f"  ✗ FAILED: {e}")
        failed += 1

    # 7. Multi-frame Figma prefetch
    print("[7/7] Multi-frame Figma prefetch logic...")
    try:
        import importlib
        mod = importlib.import_module("agent")
        source = open(mod.__file__).read()
        # Verify: no "break  # Only take the FIRST frame"
        assert "Only take the FIRST frame" not in source, "Still limited to first frame!"
        assert "MAX_FRAMES" in source
        print("  ✓ OK (all frames fetched, MAX_FRAMES cap)")
        passed += 1
    except Exception as e:
        print(f"  ✗ FAILED: {e}")
        failed += 1

    print(f"\n=== RESULTS: {passed}/{total} passed, {failed} failed ===")
    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(run_tests())
    sys.exit(0 if success else 1)
