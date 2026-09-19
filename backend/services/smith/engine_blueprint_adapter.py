"""Smith's view of the Blueprint the engine actually writes.

There are two Blueprint stores. `services/blueprint/` (the 20-node DAG) writes
``.forge/blueprint/current.json``; Smith's own `Blueprint` reads
``.forge/blueprint.json``. Different files, and nothing writes the second — so
on a project with a fully generated application Smith loaded an EMPTY
blueprint, concluded there was nothing to reason about, and routed every
message to bootstrap.

That is why a rename answered with the bootstrap seam message even after
`understand_ask` and `move_dispatcher` were wired: iteration was never reached.
§8's memory layer 2 pointed at a file that does not exist, which quietly
disabled §16's clarification and §114's Prompt-to-Change along with it.

This maps one into the other. An adapter rather than a second writer: the
engine's document stays authoritative and Smith reads a projection of it, so
the two cannot drift into disagreeing about what the application is.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def engine_doc_path(output_dir: str) -> Path:
    return Path(output_dir) / ".forge" / "blueprint" / "current.json"


def load_engine_doc(output_dir: str) -> dict[str, Any] | None:
    """The engine's Blueprint, or None when this project has no generated app."""
    path = engine_doc_path(output_dir)
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # Unreadable is treated as absent: Smith falls back to its own file
        # and, failing that, to an empty blueprint — which is what it did
        # before this adapter existed.
        return None
    return doc if isinstance(doc, dict) else None


def _live(items: Any) -> list[dict]:
    return [i for i in (items or [])
            if isinstance(i, dict) and i.get("status") != "SUPERSEDED"]


def _step_lines(w: dict[str, Any], role_names: dict[str, str]) -> list[str]:
    """A workflow's steps as one short line each — what it changes, who it
    tells, who it asks, when it refuses. The engine's own step graph is the
    source; nothing here is inferred."""
    def role(v: Any) -> str:
        return ", ".join(role_names.get(x.strip(), x.strip()) for x in str(v or "").split(",") if x.strip())

    out: list[str] = []
    for st in w.get("steps") or []:
        if not isinstance(st, dict):
            continue
        c = st.get("config") if isinstance(st.get("config"), dict) else {}
        kind, act = str(st.get("type") or ""), str(c.get("actionType") or "")
        line = ""
        if act == "send_notification" or act == "send_email":
            who = role(c.get("recipientRole") or c.get("toRole")) or str(c.get("recipient") or c.get("to") or "")
            line = f"notifies {who or 'someone'}: \"{str(c.get('message') or c.get('subject') or '')[:90]}\""
        elif act in ("db_update", "db_insert", "db_delete"):
            vals = c.get("values") or c.get("sets") or {}
            shown = ", ".join(f"{k}={v}" for k, v in list(vals.items())[:3]) if isinstance(vals, dict) else ""
            verb = {"db_update": "updates", "db_insert": "creates a row in", "db_delete": "deletes from"}[act]
            line = f"{verb} {c.get('table') or 'a record'}" + (f" ({shown})" if shown else "")
        elif kind in ("approval", "user_task", "assignment", "task_pool"):
            line = f"asks {role(c.get('assigneeRole') or c.get('assignTarget')) or 'someone'} to {kind.replace('_', ' ')}"
        elif kind in ("end", "end_event") and c.get("refused"):
            line = f"refuses: \"{str(c.get('message') or '')[:90]}\""
        if line:
            out.append(line)
    return out[:8]


def to_smith_fields(doc: dict[str, Any]) -> dict[str, Any]:
    """The engine's document in the shape Smith's `Blueprint` holds.

    Only what Smith reasons over: the domain it is working in, the entities,
    the workflows, and the pages. `pick_relevant_slice` and
    `blueprint_to_context` read these, and `understand_ask` needs the pages
    most of all — its `target_file` has to name a route that exists.
    """
    app = doc.get("application") or {}
    product = doc.get("product") or {}
    entities = (doc.get("data") or {}).get("entities")
    role_names = {str(r.get("id")): str(r.get("name")) for r in _live(doc.get("roles")) if r.get("id")}
    pages_by_id = {str(p.get("id")): p for p in _live(doc.get("pages"))}

    domain = {
        "name": app.get("domain") or product.get("domain") or "",
        "primary_actors": [
            str(r.get("name") or r.get("id") or "")
            for r in _live(doc.get("roles"))
        ],
        "core_verbs": [
            str(w.get("name") or "") for w in _live(doc.get("workflows"))
        ][:8],
        "distinctive_shape": app.get("description") or "",
        "why": app.get("description") or "",
    }

    return {
        "domain": domain,
        # WHAT THE APP MUST DO, AND WHERE EACH LINE CAME FROM. Smith answers
        # questions from this context, and "which requirements came from the
        # document I uploaded?" has its answer in `requirements[].evidence`
        # — nowhere else. Without them here Smith could only guess from the
        # brief's prose.
        "requirements": [
            {
                "id": r.get("id"),
                "description": r.get("description") or "",
                "evidence": [
                    {"type": e.get("type"), "source": e.get("source")}
                    for e in (r.get("evidence") or []) if isinstance(e, dict)
                ],
            }
            for r in _live(doc.get("requirements"))
        ],
        "entities": [
            {
                "name": e.get("name"),
                "table": e.get("table"),
                "purpose": e.get("purpose") or "",
                "key_fields": [f.get("name") for f in (e.get("fields") or [])
                               if isinstance(f, dict) and f.get("name")],
                # THE FIELDS THEMSELVES, NOT ONLY THEIR NAMES. Asked to add
                # format validation on a telephone number, Smith asked whether
                # the field existed — it could not see that it did, because
                # the context printed the entity's name and table and nothing
                # else. A type says as much as a name here: "is it text or a
                # number" is the next question after "is it there".
                "fields": [
                    {"name": f.get("name"), "type": f.get("type"),
                     "required": bool(f.get("required")),
                     "enumValues": list(f.get("enumValues") or [])}
                    for f in (e.get("fields") or [])
                    if isinstance(f, dict) and f.get("name")
                ],
                "why_shaped_this_way": e.get("purpose") or "",
            }
            for e in _live(entities)
        ],
        # WHO DOES WHAT, NOT ONLY WHAT IS CALLED WHAT. The workflows reached
        # Smith as a name and a purpose, so asked where a member's identity
        # verification goes, it answered — three times — that nothing says,
        # while the submit step notified the Admin role and the Admin's
        # verification page ran Approve and Reject (0l133sp2).
        "workflows": [
            {
                "name": w.get("name"),
                "purpose": w.get("purpose") or "",
                "trigger": (w.get("trigger") or {}).get("kind") or "manual",
                "why": w.get("purpose") or "",
                "run_from": [str((pages_by_id.get(str(x)) or {}).get("route") or x)
                             for x in w.get("launchedFrom") or []],
                "run_by": sorted({role_names.get(str(u), str(u))
                                  for x in w.get("launchedFrom") or []
                                  for u in (pages_by_id.get(str(x)) or {}).get("users") or []}),
                "steps": _step_lines(w, role_names),
            }
            for w in _live(doc.get("workflows"))
        ],
        # The rules already in force, so "add a rule that…" can be answered
        # with "that one is already there" instead of a question.
        "business_rules": [
            {"name": r.get("name"), "statement": r.get("statement"),
             "entity": r.get("entity"), "when": r.get("when")}
            for r in _live(doc.get("businessRules"))
        ],
        "pages": [
            {
                "route": p.get("route"),
                # The path the projection writes, which is what
                # `understand_ask` returns as `target_file` and what the move
                # scopes against. Derived the same way the projection derives
                # it, so the two agree.
                "schema_path": _schema_path(str(p.get("route") or "")),
                "role": p.get("name") or p.get("id") or "",
                # Who may open it: "Member Verification Detail — Admin only".
                "who": [role_names.get(str(u), str(u)) for u in p.get("users") or []],
                "access": p.get("access") or "",
                "notable_choices": [],
            }
            for p in _live(doc.get("pages"))
        ],
    }


def connection_lines(doc: dict[str, Any], output_dir: str) -> list[dict[str, Any]]:
    """Each outside service, and whether it is connected or only declared.

    Two halves, from two places. The DECLARATION — what service, which
    variables carry its credential — is in the document. Whether those
    variables are SET is in the platform's credential store (or this
    environment), which no document can know; `platform_secrets.keys_set_for`
    answers it with NAMES and never touches a value.

    The store is asked only about a service that claims to serve a runtime
    action. A row with no `serves` is a note for a developer: it is declared,
    it is reported as declared, and there is nothing to look up.
    """
    from services.smith.email_connect import LIVE_KEY, SERVES, sending_steps

    rows = [i for i in (doc.get("integrations") or [])
            if isinstance(i, dict) and i.get("status") not in ("DEPRECATED", "SUPERSEDED")]
    steps = [f"{step} in {wf}" for wf, step in sending_steps(doc)]
    if not rows and not steps:
        return []

    serving = [r for r in rows if str(r.get("serves") or "").strip()]
    set_keys: set[str] = set()
    if serving and output_dir:
        from services.platform_secrets import keys_set_for

        keys = [str(k) for r in serving for k in r.get("secretRefs") or []]
        set_keys = keys_set_for(output_dir, sorted(set(keys)))

    out: list[dict[str, Any]] = []
    for row in rows:
        serves = str(row.get("serves") or "").strip()
        keys = [str(k) for k in row.get("secretRefs") or []]
        live = LIVE_KEY.get(str(row.get("provider") or ""), "")
        # A ROW CAN CLAIM TO SERVE SOMETHING THERE IS NO ADAPTER FOR — a
        # hand-authored Blueprint saying `provider: "mailchimp"`. There is no
        # key whose presence would make it work, so it is what it is: a
        # declaration. The projection drops it for the same reason.
        if serves and not live:
            serves = ""
        out.append({
            "gap": False,
            "name": str(row.get("name") or ""),
            "kind": str(row.get("kind") or ""),
            "provider": str(row.get("provider") or ""),
            "serves": serves,
            "secret_names": keys,
            # NAMES, both of them. A value never enters this context any more
            # than it enters the Blueprint (§42).
            "set_names": [k for k in keys if k in set_keys],
            "connected": bool(serves) and live in set_keys,
            "needs": live,
            "sending_steps": steps if serves == SERVES else [],
        })
    if steps and not any(i["serves"] == SERVES for i in out):
        # A GAP IS A FACT ABOUT THIS APPLICATION, not the absence of one.
        # Steps that send email and no service to send through is the state
        # behind "the confirmation email never came", and a context that
        # simply omitted email left Smith with nothing to say about it.
        out.append({"gap": True, "name": "", "kind": "email", "provider": "",
                    "serves": SERVES, "secret_names": [], "set_names": [],
                    "connected": False, "needs": "", "sending_steps": steps})
    return out


def _schema_path(route: str) -> str:
    body = (route or "/").strip("/")
    return f"src/schemas/{body or 'home'}.json"
