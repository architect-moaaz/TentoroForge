"""IR Compiler Service — wraps the TypeScript IR compiler as a subprocess.

Calls the Node.js compiler to convert AppIR JSON → TSX files,
then writes them to the output directory.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Path to the compiler package
_PACKAGES_DIR = Path(__file__).resolve().parent.parent.parent / "packages"
_COMPILER_DIR = _PACKAGES_DIR / "compiler"
_COMPILER_SCRIPT = _COMPILER_DIR / "dist" / "index.js"

# Path to the patterns package
_PATTERNS_DIR = _PACKAGES_DIR / "patterns"
_PATTERNS_SCRIPT = _PATTERNS_DIR / "dist" / "generate-app.js"


class IRCompileError(Exception):
    """Raised when the IR compiler fails."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__(f"IR compilation failed with {len(errors)} error(s)")


async def generate_ir_from_spec(app_spec: dict[str, Any]) -> dict[str, Any]:
    """Run the pattern library to generate AppIR from an AppSpec.

    Args:
        app_spec: The AppSpec dict (from ir_adapter.plan_to_app_spec).

    Returns:
        The complete AppIR dict.
    """
    script = f"""
import {{ generateApp }} from '{_PATTERNS_DIR}/dist/generate-app.js';
const spec = {json.dumps(app_spec)};
const ir = generateApp(spec);
process.stdout.write(JSON.stringify(ir));
"""
    result = await _run_node(script)
    return json.loads(result)


async def compile_ir(ir: dict[str, Any]) -> dict[str, Any]:
    """Compile an AppIR to file map.

    Args:
        ir: The complete AppIR dict.

    Returns:
        Dict with 'files' (path→content), 'errors', 'warnings'.
    """
    script = f"""
import {{ compileWithNav }} from '{_COMPILER_DIR}/dist/index.js';
const ir = {json.dumps(ir)};
const result = compileWithNav(ir);
process.stdout.write(JSON.stringify(result));
"""
    result = await _run_node(script)
    return json.loads(result)


async def generate_and_compile(app_spec: dict[str, Any]) -> dict[str, Any]:
    """Full pipeline: AppSpec → AppIR → compiled files.

    Args:
        app_spec: The AppSpec dict.

    Returns:
        Dict with 'ir' (the AppIR), 'files' (path→content), 'errors', 'warnings'.
    """
    # Single Node.js invocation for both steps
    script = f"""
import {{ generateApp }} from '{_PATTERNS_DIR}/dist/generate-app.js';
import {{ compileWithNav }} from '{_COMPILER_DIR}/dist/index.js';
const spec = {json.dumps(app_spec)};
const ir = generateApp(spec);
const result = compileWithNav(ir);
process.stdout.write(JSON.stringify({{
    ir: ir,
    files: result.files,
    errors: result.errors,
    warnings: result.warnings,
}}));
"""
    result = await _run_node(script)
    parsed = json.loads(result)

    if parsed.get("errors"):
        raise IRCompileError(parsed["errors"])

    return parsed


async def generate_ir_from_skeletons(
    skeletons: list[dict[str, Any]],
    app_spec: dict[str, Any],
) -> dict[str, Any]:
    """Generate AppIR from LLM-generated page skeletons + AppSpec.

    Fills PlaceholderSlot nodes using the slot-filler, then returns
    the complete AppIR ready for compilation.
    """
    script = f"""
import {{ generateAppFromSkeletons }} from '{_PATTERNS_DIR}/dist/generate-app-from-skeleton.js';
import {{ compileWithNav }} from '{_COMPILER_DIR}/dist/index.js';
const skeletons = {json.dumps(skeletons)};
const spec = {json.dumps(app_spec)};
const ir = generateAppFromSkeletons(skeletons, spec);
const result = compileWithNav(ir);
process.stdout.write(JSON.stringify({{
    ir: ir,
    files: result.files,
    errors: result.errors,
    warnings: result.warnings,
}}));
"""
    result = await _run_node(script, timeout=45.0)
    parsed = json.loads(result)

    if parsed.get("errors"):
        raise IRCompileError(parsed["errors"])

    return parsed


async def write_compiled_files(
    output_dir: str,
    files: dict[str, str],
    src_prefix: str = "src",
) -> list[str]:
    """Write compiled files to the output directory.

    Args:
        output_dir: Project output directory.
        files: Map of relative paths to file contents.
        src_prefix: Prefix to add to paths (e.g., "src" → "src/app/tasks/page.tsx").

    Returns:
        List of written file paths (relative).
    """
    written: list[str] = []
    base = Path(output_dir)

    for rel_path, content in files.items():
        full_path = base / src_prefix / rel_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")
        written.append(str(Path(src_prefix) / rel_path))
        logger.info("IR compiled: %s", rel_path)

    return written


async def save_ir(output_dir: str, ir: dict[str, Any]) -> str:
    """Save the IR JSON alongside the generated code.

    Creates: output_dir/.ir/manifest.json

    Returns:
        Path to the saved IR file.
    """
    ir_dir = Path(output_dir) / ".ir"
    ir_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = ir_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(ir, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # Also save per-page IR for incremental recompile
    pages_dir = ir_dir / "pages"
    pages_dir.mkdir(exist_ok=True)
    for page in ir.get("pages", []):
        page_path = pages_dir / f"{page['$id']}.json"
        page_path.write_text(
            json.dumps(page, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    logger.info("IR saved: %s", manifest_path)
    return str(manifest_path)


def load_ir(output_dir: str) -> dict[str, Any] | None:
    """Load a previously saved IR from the output directory.

    Returns None if no IR exists.
    """
    manifest_path = Path(output_dir) / ".ir" / "manifest.json"
    if not manifest_path.exists():
        return None
    return json.loads(manifest_path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Node.js subprocess runner
# ---------------------------------------------------------------------------

async def _run_node(script: str, timeout: float = 30.0) -> str:
    """Execute a Node.js script and return stdout.

    Raises IRCompileError on non-zero exit or timeout.
    """
    proc = await asyncio.create_subprocess_exec(
        "node",
        "--input-type=module",
        "-e",
        script,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "NODE_NO_WARNINGS": "1"},
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
    except asyncio.TimeoutError:
        proc.kill()
        raise IRCompileError(["IR compiler timed out"])

    if proc.returncode != 0:
        error_msg = stderr.decode("utf-8", errors="replace").strip()
        logger.error("IR compiler error: %s", error_msg)
        raise IRCompileError([f"Node.js error: {error_msg}"])

    return stdout.decode("utf-8")
