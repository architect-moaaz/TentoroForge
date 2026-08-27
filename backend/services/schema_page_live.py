"""Stop the schema-page renderer from passing an empty previewData={} to the Engine.

renderSchemaPage resolves dataSources server-side and passes them as `previewData`
for correct SSR. But form/create pages have NO dataSources, so previewData is `{}`
— and `{} !== undefined` flips the Engine into PREVIEW mode, where its workflow
dispatch is inert. Result: every create/edit form submit silently no-ops (the
single biggest "can't add records" symptom). Fix: only pass previewData when it
actually has keys, so form pages render live and dispatch real workflows.
"""
from __future__ import annotations

from pathlib import Path

_OLD = '<Engine schema={page as any} apiBaseUrl="" previewData={previewData} />'
_NEW = (
    "{(() => {\n"
    "        // Empty previewData ({}) still flips the Engine into preview mode\n"
    "        // (inert dispatch) — only pass it when we actually resolved data so\n"
    "        // form/create pages render live and can dispatch real workflows.\n"
    "        const hasPreview = Object.keys(previewData).length > 0;\n"
    '        return <Engine schema={page as any} apiBaseUrl="" live {...(hasPreview ? { previewData } : {})} />;\n'
    "      })()}"
)


def make_form_pages_live(output_dir: str | Path) -> dict:
    p = Path(output_dir) / "src" / "lib" / "schema-page.tsx"
    if not p.exists():
        return {"patched": False, "reason": "no schema-page.tsx"}
    s = p.read_text(encoding="utf-8")
    if "hasPreview" in s:
        return {"patched": False, "reason": "already live-gated"}
    if _OLD not in s:
        return {"patched": False, "reason": "Engine render line not found"}
    p.write_text(s.replace(_OLD, _NEW, 1), encoding="utf-8")
    return {"patched": True}
