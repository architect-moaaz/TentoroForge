"""The pictures a converted view refers to, rendered by Figma and kept.

`tsx.Assets` records what markup cannot draw — icons and artwork as SVG,
image fills as PNG — under the path the view refers to (`/drawn/<key>`).
This asks Figma to render each once and writes it into the app's
`public/drawn/`. A file already there is not asked for again, so a rebuild
costs nothing; one Figma will not render is reported, and its view still
renders (as an empty box the drawn size).
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PUBLIC_DIR = Path("public") / "drawn"
#: Where a project keeps them, out of reach of the app's install; assembly
#: copies them into the app (`copy_into`).
STORE_DIR = Path(".forge") / "drawn"


def _token(output_dir: str | Path) -> str:
    from services.figma.integrations import config_for, token_resolver

    ref, resolver = token_resolver(config_for(output_dir))
    try:
        return resolver.resolve(ref) or ""
    except Exception:  # noqa: BLE001 — no token is a reported gap, not a crash
        return ""


def copy_into(output_dir: str | Path, app_root: str | Path) -> int:
    """The project's drawn assets into the app's `public/drawn/`."""
    import shutil
    source = Path(output_dir) / STORE_DIR
    if not source.is_dir():
        return 0
    dest = Path(app_root) / PUBLIC_DIR
    dest.mkdir(parents=True, exist_ok=True)
    n = 0
    for f in source.iterdir():
        if f.is_file() and not (dest / f.name).is_file():
            shutil.copy2(f, dest / f.name)
            n += 1
    return n


def export(output_dir: str | Path, file_key: str, items: dict[str, tuple[str, str]]) -> dict[str, Any]:
    """Render and save every asset not already saved. ``items`` is
    ``{file name: (node id, "svg" | "png")}``. Returns what happened."""
    from services.figma_client import download_images, fetch_figma_image_urls

    out_dir = Path(output_dir) / STORE_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    wanted = {name: spec for name, spec in items.items() if not (out_dir / name).is_file()}
    if not wanted:
        return {"saved": 0, "kept": len(items), "missing": []}
    token = _token(output_dir)
    if not token:
        return {"saved": 0, "kept": len(items) - len(wanted), "missing": sorted(wanted),
                "why": "no Figma token to render the design's icons and pictures with"}

    async def run() -> dict[str, bytes]:
        got: dict[str, bytes] = {}
        for fmt in ("svg", "png"):
            ids = sorted({nid for nid, f in wanted.values() if f == fmt and nid})
            if not ids:
                continue
            urls = await fetch_figma_image_urls(file_key, ids, token, format=fmt, scale=1.0 if fmt == "svg" else 2.0)
            files = await download_images(urls)
            for name, (nid, f) in wanted.items():
                if f == fmt and nid in files:
                    got[name] = files[nid]
        return got

    try:
        got = asyncio.run(run())
    except RuntimeError:                         # already inside a loop
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(1) as pool:
            got = pool.submit(asyncio.run, run()).result()
    except Exception as exc:  # noqa: BLE001 — pictures are a help, never the reason a view fails
        logger.warning("[drawn] assets not rendered: %s", exc)
        return {"saved": 0, "kept": len(items) - len(wanted), "missing": sorted(wanted), "why": str(exc)[:200]}
    for name, data in got.items():
        (out_dir / name).write_bytes(data)
    return {"saved": len(got), "kept": len(items) - len(wanted), "missing": sorted(set(wanted) - set(got))}
