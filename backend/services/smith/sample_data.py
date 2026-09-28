"""“The sample areas are wrong — make them real India and Sri Lanka ones.”

The demo rows an application starts with are derived from its definition:
example k of every text field of a record type is sample record k
(`projection.seed_rows`). When those examples are wrong — out of the app's
scope, or written field by field so a country sits beside another country's
state (Test2, 2026-09-28: Nepal with Uttar Pradesh) — the rows are wrong, and
nothing Smith could do reached them: the seeder skips a table that has rows.

This re-authors the examples of one record type from what the person said
and what the requirements set, row by row, and replaces EXACTLY the old
sample rows in the running database: a row is a sample row when every text
field equals the sample record the old examples derived. Rows people entered
never match that and are never touched; a sample row another record points
at is kept and said.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from services.llm_client import tell
from services.smith.section_change import SectionChangeError, find_named

logger = logging.getLogger(__name__)

_TEXT = ("string", "text", "varchar")

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["fields"],
    "properties": {
        "fields": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "examples"],
                "properties": {
                    "name": {"type": "string"},
                    "examples": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    },
}

SYSTEM = (
    "You write the sample records an application starts with, for ONE record "
    "type. You are given its text fields, their current examples, the "
    "application's requirements and what the person asked.\n\n"
    "EXAMPLES ARE READ ROW BY ROW. Example k of every field together is sample "
    "record k, so every field gets the same number of examples (six to eight), "
    "in the same order, and each record is true as a whole: a place is in the "
    "region beside it, an amount fits its item. Every value stays inside the "
    "scope the requirements and the person set — the places, kinds and ranges "
    "this application is for, not their neighbours. Realistic values from the "
    "application's own world, never placeholders.\n\n"
    "Return every text field given, by its exact name."
)


def _client() -> Any:
    from services.blueprint.executors import AGENT_MODEL, AnthropicModel
    return AnthropicModel(model=AGENT_MODEL, effort="medium")


def text_fields(entity: dict) -> list[dict]:
    return [f for f in (entity.get("fields") or [])
            if isinstance(f, dict) and str(f.get("type") or "text").lower() in _TEXT
            and not f.get("primaryKey") and not f.get("references") and not f.get("sensitive")
            and f.get("name")]


def author(doc: dict, entity: dict, change: str, *, client: Any = None) -> dict[str, list[str]]:
    """New examples, one list per text field, all the same length."""
    fields = text_fields(entity)
    if not fields:
        raise SectionChangeError(f"{entity.get('name')} has no text fields with sample values to change.")
    user = json.dumps({
        "recordType": entity.get("name"),
        "fields": [{"name": f["name"], "examples": f.get("examples") or []} for f in fields],
        "requirements": [r.get("description") for r in (doc.get("requirements") or [])
                         if isinstance(r, dict) and r.get("status") not in ("DEPRECATED", "SUPERSEDED")],
        "screens": [p.get("purpose") for p in (doc.get("pages") or [])
                    if isinstance(p, dict) and p.get("purpose") and p.get("status") != "DEPRECATED"],
        "asked": change or "Make the sample records true as a whole and inside the app's scope.",
    }, ensure_ascii=False)
    raw = (client or _client())(system=SYSTEM, user=user, schema=SCHEMA)
    try:
        got = raw if isinstance(raw, dict) else json.loads(str(getattr(raw, "text", raw)))
    except ValueError:
        raise SectionChangeError("The new sample values came back unreadable, so I changed nothing.") from None
    wanted = {f["name"] for f in fields}
    lists = {str(x.get("name")): [str(v).strip() for v in (x.get("examples") or []) if str(v).strip()]
             for x in (got.get("fields") or []) if isinstance(x, dict) and x.get("name") in wanted}
    lists = {k: v for k, v in lists.items() if v}
    if not lists:
        raise SectionChangeError("The new sample values did not come back for any field, so I changed nothing.")
    # ROW BY ROW OR NOT AT ALL. Lists of different lengths are what paired
    # Nepal with Uttar Pradesh; the shortest length is the number of records
    # every field can agree on.
    n = min(len(v) for v in lists.values())
    return {k: v[:n] for k, v in lists.items()}


def _columns(url: str, table: str, names: list[str]) -> dict[str, str]:
    from services.smith.data_export import existing_columns
    have = existing_columns(url, table)
    by_norm = {re.sub(r"[^a-z0-9]", "", c.lower()): c for c in have}
    out = {}
    for n in names:
        actual = n if n in have else by_norm.get(re.sub(r"[^a-z0-9]", "", n.lower()))
        if actual:
            out[n] = actual
    return out


def replace_rows(url: str, table: str, text_names: list[str],
                 old: list[dict], new: list[dict]) -> dict:
    """Delete the rows that are exactly an old sample record, insert the new
    ones. Returns counts and what was kept."""
    import psycopg2
    from psycopg2 import sql as _sql

    names = sorted({k for r in new for k in r} | set(text_names))
    cols = _columns(url, table, names)
    match_on = [n for n in text_names if n in cols]
    removed = kept = inserted = 0
    failed: list[str] = []
    with psycopg2.connect(url) as conn:
        with conn.cursor() as cur:
            for row in old:
                keys = [n for n in match_on if row.get(n) is not None]
                if not keys:
                    continue
                cur.execute("SAVEPOINT s")
                try:
                    cur.execute(
                        _sql.SQL("DELETE FROM {t} WHERE {w}").format(
                            t=_sql.Identifier(table),
                            w=_sql.SQL(" AND ").join(
                                _sql.SQL("{}::text = %s").format(_sql.Identifier(cols[n])) for n in keys)),
                        [str(row[n]) for n in keys])
                    removed += cur.rowcount
                    cur.execute("RELEASE SAVEPOINT s")
                except psycopg2.Error:
                    # Another record points at it: it stays, and is said.
                    cur.execute("ROLLBACK TO SAVEPOINT s")
                    kept += 1
            for i, row in enumerate(new):
                values: dict[str, Any] = {}
                for k, v in row.items():
                    if k not in cols or v is None:
                        continue
                    m = re.fullmatch(r"ref:(\w+)\[(\d+)\]", str(v)) if isinstance(v, str) else None
                    if m:
                        cur.execute(_sql.SQL("SELECT id FROM {} ORDER BY ctid").format(_sql.Identifier(m.group(1))))
                        ids = [r[0] for r in cur.fetchall()]
                        if not ids:
                            continue
                        v = ids[int(m.group(2)) % len(ids)]
                    values[cols[k]] = v
                if not values:
                    continue
                cur.execute("SAVEPOINT s")
                try:
                    cur.execute(
                        _sql.SQL("INSERT INTO {t} ({c}) VALUES ({p})").format(
                            t=_sql.Identifier(table),
                            c=_sql.SQL(", ").join(_sql.Identifier(c) for c in values),
                            p=_sql.SQL(", ").join(_sql.Placeholder() for _ in values)),
                        list(values.values()))
                    inserted += 1
                    cur.execute("RELEASE SAVEPOINT s")
                except psycopg2.Error as exc:
                    cur.execute("ROLLBACK TO SAVEPOINT s")
                    failed.append(f"record {i + 1}: {str(exc).splitlines()[0][:160]}")
    return {"removed": removed, "kept": kept, "inserted": inserted, "failed": failed}


def refresh(svc: Any, output_dir: str, entity_ref: str, change: str = "", *,
            client: Any = None, reasoning: Any = None) -> dict:
    from services.blueprint.projection import project_seed, seed_rows, to_snake
    from services.blueprint.schema_push import database_url as app_database_url
    from services.smith.data_import import database_url, entities_of, imports_of

    entities = entities_of(svc.doc)
    ent = find_named(entities, entity_ref, id_prefix="ENT-")
    if ent is None:
        raise SectionChangeError(f"I cannot tell which record type {entity_ref!r} means. "
                                 f"The app has: {', '.join(str(e.get('name')) for e in entities)}.")
    if any(str(i.get("entity")) == str(ent.get("id")) for i in imports_of(svc.doc)):
        raise SectionChangeError(f"{ent.get('name')} holds data you imported, not sample records, "
                                 "so there are no sample records to replace.")
    table = str(ent.get("table") or to_snake(str(ent.get("name") or "")))
    old_rows = seed_rows(svc.doc).get(table) or []
    tell(reasoning, f"Writing new sample {ent.get('name')} records, row by row.", "step")
    lists = author(svc.doc, ent, change, client=client)

    before = svc.snapshot()
    for f in ent.get("fields") or []:
        if f.get("name") in lists:
            f["examples"] = lists[f["name"]]
    svc.validate()
    svc.commit(user_request=change or f"refresh the sample {ent.get('name')} records",
               smith_interpretation=f"re-author {ent.get('name')}'s sample values row by row",
               before=before, affected=[str(ent.get("id"))])
    new_rows = seed_rows(svc.doc).get(table) or []

    app_root = Path(output_dir) / "app"
    edited: list[str] = []
    if (app_root / "src" / "db").is_dir():
        project_seed(svc.doc, str(app_root))
        edited.append("app/src/db/seed.json")
    url = database_url(output_dir) or app_database_url(app_root)
    db: dict = {"reason": "its database is not running"} if not url else {}
    if url:
        try:
            db = replace_rows(url, table, [f["name"] for f in text_fields(ent)], old_rows, new_rows)
        except Exception as exc:  # noqa: BLE001 — the definition changed; the database is said
            logger.exception("[sample_data] %s", table)
            db = {"reason": f"{type(exc).__name__}: {str(exc)[:200]}"}
    return {"entity": str(ent.get("name")), "fields": lists, "records": len(next(iter(lists.values()))),
            "db": db, "edited_paths": edited}


def summary_of(out: dict) -> str:
    first = [f"{k}: {v[0]}" for k, v in out["fields"].items()]
    head = (f"{out['entity']}'s sample records are rewritten, {out['records']} of them, each true as a "
            f"whole (the first is {', '.join(first)}).")
    db = out["db"]
    if "reason" in db:
        return head + f" The running app still shows the old ones: {db['reason']}. They are replaced the next time it seeds."
    tail = f" In the running app, {db['removed']} old sample row(s) were replaced by {db['inserted']}."
    if db.get("kept"):
        tail += f" {db['kept']} old sample row(s) stayed because other records point at them."
    if db.get("failed"):
        tail += f" {len(db['failed'])} could not be added ({db['failed'][0]})."
    return head + tail + " Rows people entered were not touched. Reload the preview to see them."


def run(output_dir: str, *, entity: str = "", change: str = "", reasoning: Any = None,
        client: Any = None) -> dict:
    from services.blueprint.service import BlueprintService
    try:
        svc = BlueprintService.load(output_dir=str(output_dir))
    except FileNotFoundError:
        return {"applied": False, "edited_paths": [], "reason": "this project has no definition yet."}
    try:
        out = refresh(svc, output_dir, entity, change, client=client, reasoning=reasoning)
    except SectionChangeError as exc:
        return {"applied": False, "edited_paths": [], "reason": str(exc)}
    except Exception as exc:  # noqa: BLE001
        logger.exception("[sample_data] failed")
        return {"applied": False, "edited_paths": [], "reason": f"{type(exc).__name__}: {exc}"}
    return {"applied": True, "edited_paths": out["edited_paths"], "diff_summary": summary_of(out),
            "reason": "", **{k: v for k, v in out.items() if k != "edited_paths"}}


__all__ = ["author", "refresh", "replace_rows", "run", "summary_of", "text_fields"]
