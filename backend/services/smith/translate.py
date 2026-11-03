"""The drawn words in another language, filled in one step (`translate_words`, 2026-10-31).

An application drawn from a design shows the drawing's own words, and a
second language is a table beside them (`product.words[tag]`, read at
runtime by `DrawnWords`). Nothing wrote that table: DITANS's 6,533 Arabic
words were translated by hand, in batches, in parallel. This is that sweep:
the words not yet in the table, in batches, each batch one model call with
the application's name and purpose as context, all landing as one version.
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import logging
from pathlib import Path
from typing import Any

from services.llm_client import tell

logger = logging.getLogger(__name__)

#: Words per call, and calls at once.
BATCH = 150
WORKERS = 6

SCHEMA = {"type": "object", "additionalProperties": False, "required": ["words"], "properties": {
    "words": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                         "required": ["source", "text"],
                                         "properties": {"source": {"type": "string"}, "text": {"type": "string"}}}}}}


def _system(doc: dict, tag: str) -> str:
    product = doc.get("product") or {}
    name = (doc.get("application") or {}).get("name") or product.get("name") or "the application"
    what = product.get("summary") or product.get("purpose") or product.get("description") or ""
    return (f"You translate the interface words of {name}" + (f" — {what}" if what else "") + f" — into the "
            f"language `{tag}`. Each word or phrase is a label, a heading, a button, a menu entry or a sentence "
            "on a screen: translate it as that screen would say it, short where the source is short, in the "
            "terms that field uses. Keep as they are: names of people, organisations and products, codes, "
            "numbers, units, e-mail addresses, and placeholders like {name} or %s. A source already in the "
            "target language is returned unchanged. Return every source exactly as given, with its `text`.")


def translate_words(output_dir: str, tag: str = "", *, client: Any = None, reasoning: Any = None) -> dict:
    """Fill `product.words[tag]` with every drawn word it lacks; one version,
    projected. Without `tag`, every language the app is shown in besides
    its own."""
    from services.blueprint.languages import languages, project_languages
    from services.blueprint.service import BlueprintService
    from services.drawn.words import untranslated

    def finding(text: str) -> dict:
        return {"applied": False, "said": text, "finding": text, "touched": [], "version": 0}

    try:
        svc = BlueprintService.load(output_dir=str(output_dir))
    except FileNotFoundError:
        return finding("This project has no Blueprint, so there are no words to translate.")
    shown = languages(svc.doc)
    tags = [t for t in ([tag] if tag else shown[1:]) if t]
    if not tags:
        return finding("The application is shown in one language only. To add one, change `product.languages` "
                       "(`edit_definition` on `product`), then translate.")
    if any(t not in shown[1:] for t in tags):
        return finding(f"`{tag}` is not a language the application is shown in besides its own; it shows "
                       + ", ".join(shown) + ".")
    if not any(isinstance(v, dict) for v in svc.doc.get("drawnViews") or []):
        return finding("This application has no drawn screens; its words are translated where its screens are "
                       "written (`edit_pages`), not in the drawn words table.")
    if client is None:
        from services.blueprint.executors import DEFAULT_MODEL, AnthropicModel
        client = AnthropicModel(model=DEFAULT_MODEL, effort="low")
    from services.blueprint.executors import RunUsage
    usage = RunUsage.for_app(svc, phase="change")

    def batch(t: str, words: list[str]) -> tuple[str, dict[str, str], str]:
        user = "Translate each of these, one per line of JSON:\n" + json.dumps(words, ensure_ascii=False)
        try:
            reply = client(system=_system(svc.doc, t), user=user, schema=SCHEMA)
            try:
                usage.record(node="translate", agent="translator", usage=getattr(reply, "usage", None), elapsed_s=0)
            except Exception:  # noqa: BLE001 — accounting never fails a translation
                pass
            body = json.loads(str(getattr(reply, "text", reply)))
        except Exception as exc:  # noqa: BLE001 — one batch, not the sweep
            return t, {}, f"{type(exc).__name__}: {str(exc)[:160]}"
        asked = set(words)
        got = {str(w.get("source")): str(w.get("text") or "").strip() for w in body.get("words") or []
               if isinstance(w, dict)}
        return t, {k: v for k, v in got.items() if k in asked and v}, ""

    jobs = [(t, left[i:i + BATCH]) for t in tags for left in [untranslated(svc.doc, t)]
            for i in range(0, len(left), BATCH)]
    if not jobs:
        return finding("Every drawn word is already translated into " + ", ".join(tags) + ".")
    tell(reasoning, f"Translating {sum(len(w) for _t, w in jobs)} words into {', '.join(tags)}", "step")
    found: dict[str, dict[str, str]] = {t: {} for t in tags}
    problems: list[str] = []
    with cf.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for t, got, why in pool.map(lambda job: batch(*job), jobs):
            found[t].update(got)
            if why:
                problems.append(why)
    if not any(found.values()):
        return finding("No word was translated: " + "; ".join(problems[:3]))
    before = svc.snapshot()
    product = svc.doc.setdefault("product", {})
    table = product.setdefault("words", {})
    for t, got in found.items():
        table[t] = {**(table.get(t) or {}), **got}
    svc.validate()
    record = svc.commit(user_request=f"translate the drawn words into {', '.join(tags)}",
                        smith_interpretation="fill product.words", before=before, affected=[])
    try:
        project_languages(svc.doc, Path(output_dir) / "app")
    except Exception as exc:  # noqa: BLE001 — the table is kept; the next projection writes it
        logger.warning("[translate] words kept but not projected: %s", exc)
    left = {t: len(untranslated(svc.doc, t)) for t in tags}
    said = (f"Translated {sum(len(g) for g in found.values())} words (version {record['version']}): "
            + "; ".join(f"{t} {len(found[t])}" + (f", {left[t]} still untranslated" if left[t] else ", all done")
                        for t in tags) + ".")
    return {"applied": True, "said": said, "version": int(record["version"]), "touched": [],
            "finding": ("Some batches failed: " + "; ".join(problems[:3])) if problems else ""}


__all__ = ["BATCH", "translate_words"]
