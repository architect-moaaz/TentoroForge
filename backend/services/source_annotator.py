"""Source file annotator — adds data-source-file/line attributes to JSX.

These attributes allow the bridge script to report which source file and line
a clicked DOM element originated from, enabling the visual editor to jump
to the correct location for edits.

Primary implementation uses a Babel-based Node.js script (annotate-source.mjs)
for accurate AST-level annotation of ALL JSX elements. Falls back to the
original regex approach if Babel deps are missing or the script fails.
"""

import asyncio
import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

ANNOTATOR_SCRIPT = Path(__file__).parent.parent / "static" / "annotate-source.mjs"

_SOURCE_ATTR_RE = re.compile(r'data-source-file="[^"]*"')

BABEL_DEPS = [
    "@babel/parser",
    "@babel/traverse",
    "@babel/generator",
    "@babel/types",
]


async def _ensure_babel_deps(output_dir: str) -> bool:
    """Install Babel dependencies if missing. Returns True if available."""
    out = Path(output_dir)
    # Quick check: if node_modules/@babel/parser exists, assume deps are present
    if (out / "node_modules" / "@babel" / "parser").exists():
        return True

    logger.info("Installing Babel dependencies for AST annotation...")
    proc = await asyncio.create_subprocess_exec(
        "npm", "install", "--save-dev", "--no-audit", "--no-fund", *BABEL_DEPS,
        cwd=output_dir,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.warning("Failed to install Babel deps: %s", stderr.decode()[:500])
        return False
    return True


async def annotate_source_files(output_dir: str) -> int:
    """Add data-source-file and data-source-line attributes to JSX elements.

    Uses the Babel AST annotator for accurate, comprehensive annotation.
    Falls back to the regex approach if Babel is unavailable.
    """
    if not await _ensure_babel_deps(output_dir):
        logger.info("Falling back to regex annotation")
        return _regex_annotate_fallback(output_dir)

    try:
        proc = await asyncio.create_subprocess_exec(
            "node", str(ANNOTATOR_SCRIPT), "annotate", output_dir,
            cwd=output_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            logger.warning(
                "Babel annotator failed (rc=%d): %s",
                proc.returncode,
                stderr.decode()[:500],
            )
            return _regex_annotate_fallback(output_dir)

        result = json.loads(stdout.decode())
        count = result.get("annotated", 0)
        files = result.get("files", [])
        logger.info("AST annotation: %d elements across %d files", count, len(files))
        return len(files)

    except Exception as e:
        logger.warning("Babel annotator error: %s", e)
        return _regex_annotate_fallback(output_dir)


async def strip_source_annotations(output_dir: str) -> int:
    """Remove all data-source-* attributes from JSX files.

    Uses the Babel AST stripper when available, falls back to regex.
    """
    # Check if Babel deps are present (don't install just for stripping)
    out = Path(output_dir)
    has_babel = (out / "node_modules" / "@babel" / "parser").exists()

    if not has_babel:
        return _regex_strip_fallback(output_dir)

    try:
        proc = await asyncio.create_subprocess_exec(
            "node", str(ANNOTATOR_SCRIPT), "strip", output_dir,
            cwd=output_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            logger.warning(
                "Babel stripper failed (rc=%d): %s",
                proc.returncode,
                stderr.decode()[:500],
            )
            return _regex_strip_fallback(output_dir)

        result = json.loads(stdout.decode())
        count = result.get("stripped", 0)
        logger.info("AST strip: %d files cleaned", count)
        return count

    except Exception as e:
        logger.warning("Babel stripper error: %s", e)
        return _regex_strip_fallback(output_dir)


# --- Regex fallbacks (original implementation) ---


def _regex_annotate_fallback(output_dir: str) -> int:
    """Regex-based annotation — only tags root JSX return elements."""
    out = Path(output_dir)
    count = 0
    for pattern in ["src/app/**/*.tsx", "src/components/**/*.tsx"]:
        for tsx_file in out.glob(pattern):
            if _annotate_file_regex(tsx_file, out):
                count += 1
    return count


def _regex_strip_fallback(output_dir: str) -> int:
    """Regex-based strip of data-source-* attributes."""
    out = Path(output_dir)
    count = 0
    for pattern in ["src/app/**/*.tsx", "src/components/**/*.tsx"]:
        for tsx_file in out.glob(pattern):
            source = tsx_file.read_text(encoding="utf-8")
            if "data-source-file=" not in source:
                continue
            cleaned = re.sub(r'\s+data-source-file="[^"]*"', "", source)
            cleaned = re.sub(r'\s+data-source-line="[^"]*"', "", cleaned)
            cleaned = re.sub(r'\s+data-source-component="[^"]*"', "", cleaned)
            if cleaned != source:
                tsx_file.write_text(cleaned, encoding="utf-8")
                count += 1
    return count


def _annotate_file_regex(tsx_file: Path, base: Path) -> bool:
    """Annotate a single TSX file using regex. Returns True if modified."""
    source = tsx_file.read_text(encoding="utf-8")

    if _SOURCE_ATTR_RE.search(source):
        return False

    rel_path = str(tsx_file.relative_to(base))
    component_name = _extract_component_name(source)

    pattern = re.compile(
        r"(return\s*\(?\s*\n?\s*)(<[a-zA-Z][\w.]*)",
        re.MULTILINE,
    )

    match = pattern.search(source)
    if not match:
        return False

    tag_name = match.group(2).lstrip("<")
    if tag_name.lower() in ("html", "head"):
        return False

    line_number = source[: match.start(2)].count("\n") + 1

    attrs = f' data-source-file="{rel_path}" data-source-line="{line_number}"'
    if component_name:
        attrs += f' data-source-component="{component_name}"'

    annotated = source[: match.end(2)] + attrs + source[match.end(2) :]
    tsx_file.write_text(annotated, encoding="utf-8")
    return True


def _extract_component_name(source: str) -> str | None:
    """Extract the component name from export default function/const."""
    m = re.search(r"export\s+default\s+(?:async\s+)?function\s+(\w+)", source)
    if m:
        return m.group(1)
    m = re.search(r"export\s+default\s+(?!async\b|function\b)(\w+)", source)
    if m:
        return m.group(1)
    m = re.search(r"export\s+function\s+(\w+)", source)
    if m:
        return m.group(1)
    return None
