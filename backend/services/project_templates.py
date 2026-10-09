"""Templates made from the person's own applications — saved, listed, used again.

WHAT A TEMPLATE IS. A copy of an application's DEFINITION — its Living
Blueprint — not of its generated files. The Blueprint is the source of truth
(§115) and the app is a projection of it, so the definition is the smallest
thing that reproduces the application, the one that cannot drift from it, and
the one the CURRENT engine rebuilds: an application made from a template today
picks up every platform fix made since the template was saved, which a copy of
yesterday's files never would.

WHAT IS LEFT OUT. The parts of a Blueprint that describe *one deployment of*
the application rather than the application: approvals (consent is given per
project, never inherited), change history, the code map, runtime and
deployment state. They are written again by the build of the project that uses
the template. Everything else — requirements, records, screens, written page
code, workflows, rules, roles, design — is kept, with the ID registry beside it
so a copy keeps every artifact's identity.

WHERE IT LIVES. ``<output>/_templates/<id>/`` — ``meta.json`` (who may see it,
what it is) beside ``blueprint.json``, ``ids.json`` and the logo. On disk, like
the Blueprint it was taken from: Smith saves one from inside a turn, which runs
on a worker thread with no database session, and a template is backed up and
restored with the projects it came from.

HOW ONE IS USED. A project made from a template carries it, staged, in
``.forge/template/`` until Smith learns what the person wants (see
``services.smith4.definition``):

* ``exact``   — the definition becomes this project's, as it stands. The build
  that follows authors nothing: every agent's section is already written, so
  only the deterministic steps run (see :func:`exact_build_pending`).
* ``adapt``   — a new definition is authored from what the person says is
  different, with the template given to the agents as a reference document and
  its look kept unless they asked for a new one.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: The Blueprint sections that belong to one deployment of an application, not
#: to the application. Dropped when a template is taken; the build of the
#: project that uses it writes them again.
PER_PROJECT_SECTIONS = ("approvals", "changeHistory", "codeMap", "runtime", "deployment")

#: Where a project keeps the template it was made from, until it is used.
STAGE_DIR = Path(".forge") / "template"

MODE_EXACT = "exact"
MODE_ADAPT = "adapt"

#: Status of a staged template in a project.
PENDING = "pending"
BUILT = "built"

_ID = re.compile(r"^[0-9a-f]{32}$")
#: Smith's direct edits to the app's files (`services.smith.file_edit`): part
#: of what the application IS, so an exact copy carries them.
PATCHES = "patches.json"
NAME_MAX = 120
DESCRIPTION_MAX = 2000


class TemplateError(ValueError):
    """A template cannot be saved, found or used — the message says why."""


# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #

def templates_root() -> Path:
    from services.project_service import OUTPUT_BASE
    return Path(OUTPUT_BASE) / "_templates"


def _dir(template_id: str) -> Path:
    # The id comes from a URL or a model's tool call: it is checked, never
    # joined blindly, so it cannot name a path outside the templates root.
    if not _ID.match(str(template_id or "")):
        raise TemplateError("That is not a template id.")
    return templates_root() / template_id


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), "utf-8")
    os.replace(tmp, path)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- #
# What a definition holds — the facts a gallery card and Smith speak from
# --------------------------------------------------------------------------- #

def _live(items: Any) -> list[dict]:
    return [i for i in (items or [])
            if isinstance(i, dict) and i.get("status") not in ("DEPRECATED", "SUPERSEDED")]


def summary(doc: dict) -> dict:
    """What the application is, in counts and names — no prose to parse back."""
    app = doc.get("application") or {}
    pages = _live(doc.get("pages"))
    entities = _live((doc.get("data") or {}).get("entities"))
    workflows = _live(doc.get("workflows"))
    roles = _live(doc.get("roles"))
    colors = (doc.get("designSystem") or {}).get("colors") or {}
    palette = [str(colors[k]) for k in ("primary", "secondary", "accent", "background")
               if isinstance(colors.get(k), str) and str(colors[k]).startswith("#")]
    coded = {str(r.get("page")) for r in doc.get("pageCode") or [] if isinstance(r, dict)}
    return {
        "name": str(app.get("name") or ""),
        "description": str(app.get("description") or "")[:600],
        "domain": str(app.get("domain") or ""),
        "counts": {
            "requirements": len(_live(doc.get("requirements"))),
            "pages": len(pages),
            "entities": len(entities),
            "workflows": len(workflows),
            "roles": len(roles),
            "rules": len(_live(doc.get("businessRules"))),
            "integrations": len(_live(doc.get("integrations"))),
        },
        "pages": [str(p.get("title") or p.get("route") or "") for p in pages][:16],
        "entities": [str(e.get("name") or "") for e in entities][:16],
        "workflows": [str(w.get("name") or "") for w in workflows][:16],
        "roles": [str(r.get("name") or "") for r in roles][:8],
        "palette": palette,
        "designed": bool(pages) and all(str(p.get("id")) in coded for p in pages),
    }


#: How a count is said: (key, one, many).
_COUNTED = (("pages", "screen", "screens"), ("entities", "kind of record", "kinds of record"),
            ("workflows", "process", "processes"), ("roles", "role", "roles"),
            ("requirements", "requirement", "requirements"))


def counted(counts: dict, keys: tuple[str, ...] = ("pages", "entities", "workflows", "roles")) -> str:
    """``"3 screens, 1 kind of record, 4 processes"`` — what a template holds,
    said the way a person says it."""
    parts = []
    for key, one, many in _COUNTED:
        n = counts.get(key) if key in keys else 0
        if n:
            parts.append(f"{n} {one if n == 1 else many}")
    return ", ".join(parts)


def is_defined(doc: dict) -> bool:
    """Requirements or screens — the same test the router uses for "defined"."""
    return bool(doc.get("requirements") or doc.get("pages"))


def _active_edits(output_dir: Path) -> list[dict]:
    from services.smith.file_edit import load_patches
    return [p for p in load_patches(output_dir) if p.get("status") == "active"]


def is_modelled(doc: dict) -> bool:
    """Past the product model: screens AND records exist. A template saved at
    the requirements review is a definition still to be modelled — copying it
    "exactly" copies the requirements, and the rest is authored as for any app."""
    return bool(_live(doc.get("pages")) and _live((doc.get("data") or {}).get("entities")))


# --------------------------------------------------------------------------- #
# Taking a template
# --------------------------------------------------------------------------- #

def snapshot(doc: dict) -> dict:
    """The definition without what belongs to one deployment of it, valid."""
    from services.blueprint.service import BlueprintService

    out = json.loads(json.dumps(doc))  # deep copy; the source is never touched
    for section in PER_PROJECT_SECTIONS:
        out.pop(section, None)
    out["version"] = 1
    svc = BlueprintService(output_dir=str(templates_root()))
    svc.doc = out
    svc.validate()  # a template that would not load is not saved at all
    return out


def save(*, output_dir: str | Path, org_id: str, created_by: str = "",
         created_by_name: str = "", source_project_id: str = "",
         name: str = "", description: str = "", category: str = "") -> dict:
    """Take a template of the application in `output_dir`. Returns its meta."""
    from services.blueprint.service import BlueprintService

    output_dir = Path(output_dir)
    if not (output_dir / ".forge" / "blueprint" / "current.json").is_file():
        raise TemplateError("This project has no definition yet — describe the app to Smith "
                            "first; a template is made from what it defines.")
    doc = BlueprintService.load(output_dir=output_dir).doc
    if not is_defined(doc):
        raise TemplateError("This project has no requirements or screens yet, so there is "
                            "nothing to make a template of.")
    if not str(org_id or "").strip():
        raise TemplateError("A template belongs to an organisation; none was given.")

    facts = summary(doc)
    name = (str(name or "").strip() or f"{facts['name'] or 'Application'} template")[:NAME_MAX]
    template_id = uuid.uuid4().hex
    root = _dir(template_id)
    try:
        _write_json(root / "blueprint.json", snapshot(doc))
        ids = output_dir / ".forge" / "ids.json"
        if ids.is_file():
            shutil.copyfile(ids, root / "ids.json")
        edits = _active_edits(output_dir)
        if edits:
            _write_json(root / PATCHES, edits)
        brand = output_dir / "brand"
        if brand.is_dir():
            shutil.copytree(brand, root / "brand", dirs_exist_ok=True)
        meta = {
            "id": template_id,
            "org_id": str(org_id),
            "name": name,
            "description": (str(description or "").strip() or facts["description"])[:DESCRIPTION_MAX],
            "category": str(category or facts["domain"] or "").strip()[:60],
            "created_by": str(created_by or ""),
            "created_by_name": str(created_by_name or "")[:120],
            "source_project_id": str(source_project_id or ""),
            "source_short_id": output_dir.name,
            "source_version": int(doc.get("version") or 1),
            "created_at": _now(),
            "updated_at": _now(),
            "summary": facts,
        }
        _write_json(root / "meta.json", meta)
    except Exception:
        shutil.rmtree(root, ignore_errors=True)  # never leave half a template behind
        raise
    logger.info("[templates] saved %s (%r) from %s for org %s", template_id, name,
                output_dir.name, org_id)
    return meta


# --------------------------------------------------------------------------- #
# Finding, renaming, deleting
# --------------------------------------------------------------------------- #

def get(template_id: str) -> dict | None:
    try:
        path = _dir(template_id) / "meta.json"
    except TemplateError:
        return None
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        logger.warning("[templates] unreadable meta for %s", template_id)
        return None


def list_for_org(org_id: str) -> list[dict]:
    """Every template of the organisation, newest first."""
    root = templates_root()
    if not root.is_dir():
        return []
    out = []
    for child in root.iterdir():
        meta = get(child.name) if child.is_dir() else None
        if meta and str(meta.get("org_id")) == str(org_id):
            out.append(meta)
    return sorted(out, key=lambda m: str(m.get("created_at") or ""), reverse=True)


def update(template_id: str, *, name: str | None = None, description: str | None = None) -> dict:
    meta = get(template_id)
    if not meta:
        raise TemplateError("That template does not exist.")
    if name is not None:
        if not str(name).strip():
            raise TemplateError("A template needs a name.")
        meta["name"] = str(name).strip()[:NAME_MAX]
    if description is not None:
        meta["description"] = str(description).strip()[:DESCRIPTION_MAX]
    meta["updated_at"] = _now()
    _write_json(_dir(template_id) / "meta.json", meta)
    return meta


def delete(template_id: str) -> bool:
    """Remove a template. Projects already made from it are untouched — each
    holds its own copy."""
    if not get(template_id):
        return False
    shutil.rmtree(_dir(template_id), ignore_errors=True)
    return True


def load_definition(template_id: str) -> dict:
    path = _dir(template_id) / "blueprint.json"
    if not path.is_file():
        raise TemplateError("That template's definition is missing.")
    return json.loads(path.read_text("utf-8"))


# --------------------------------------------------------------------------- #
# Using a template: staged in the project, then made into its definition
# --------------------------------------------------------------------------- #

def stage(template_id: str, output_dir: str | Path) -> dict:
    """Put the template beside a new project, waiting for Smith to use it."""
    meta = get(template_id)
    if not meta:
        raise TemplateError("That template does not exist.")
    src = _dir(template_id)
    dest = Path(output_dir) / STAGE_DIR
    dest.mkdir(parents=True, exist_ok=True)
    for f in ("blueprint.json", "ids.json", PATCHES):
        if (src / f).is_file():
            shutil.copyfile(src / f, dest / f)
    if (src / "brand").is_dir():
        shutil.copytree(src / "brand", dest / "brand", dirs_exist_ok=True)
    source = {"template_id": template_id, "name": meta["name"],
              "description": meta.get("description") or "", "summary": meta.get("summary") or {},
              "status": PENDING, "mode": "", "staged_at": _now()}
    _write_json(dest / "source.json", source)
    return source


def source_of(output_dir: str | Path) -> dict | None:
    """The template this project was made from, if any."""
    path = Path(output_dir) / STAGE_DIR / "source.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return None


def pending(output_dir: str | Path) -> dict | None:
    """A staged template Smith has not used yet."""
    src = source_of(output_dir)
    return src if src and src.get("status") == PENDING else None


def _mark(output_dir: str | Path, **changes: Any) -> dict:
    src = source_of(output_dir) or {}
    src.update(changes)
    _write_json(Path(output_dir) / STAGE_DIR / "source.json", src)
    return src


def _staged_definition(output_dir: str | Path) -> dict:
    path = Path(output_dir) / STAGE_DIR / "blueprint.json"
    if not path.is_file():
        raise TemplateError("This project's template is missing — pick it again from Templates.")
    return json.loads(path.read_text("utf-8"))


def _copy_brand(output_dir: Path) -> None:
    staged = output_dir / STAGE_DIR / "brand"
    if staged.is_dir():
        shutil.copytree(staged, output_dir / "brand", dirs_exist_ok=True)


def use_exact(output_dir: str | Path, *, app_name: str = "") -> dict:
    """The template's definition becomes this project's, as it stands.

    Identity is the project's own (its id, and the name the person gave it);
    everything the application IS comes from the template. The state is the
    product-model review: the definition is complete, so what is left is the
    person's consent to build it."""
    from services.blueprint.service import BlueprintService
    from services.smith import gates

    output_dir = Path(output_dir)
    if (output_dir / ".forge" / "blueprint" / "current.json").is_file():
        existing = BlueprintService.load(output_dir=output_dir).doc
        if is_defined(existing):
            raise TemplateError("This project already has a definition; a template can only "
                                "start a project, not replace one.")
    src = source_of(output_dir) or {}
    doc = _staged_definition(output_dir)
    app = doc.setdefault("application", {})
    app["id"] = output_dir.name
    if str(app_name or "").strip():
        app["name"] = str(app_name).strip()
    complete = is_modelled(doc)
    doc["state"] = "PLAN_REVIEW" if complete else "BLUEPRINT_REVIEW"
    doc["version"] = 1
    staged_ids = output_dir / STAGE_DIR / "ids.json"
    if staged_ids.is_file():
        (output_dir / ".forge").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(staged_ids, output_dir / ".forge" / "ids.json")
    staged_edits = output_dir / STAGE_DIR / PATCHES
    if staged_edits.is_file():
        shutil.copyfile(staged_edits, output_dir / ".forge" / PATCHES)
    _copy_brand(output_dir)

    svc = BlueprintService(output_dir=str(output_dir))
    svc.doc = doc
    svc.validate()
    svc.save()
    # The two reviews are recorded as SHOWN, so the gates panel can say what
    # changed if the person edits the definition before building. Nothing is
    # approved here: "Build app" on the card is the consent, as for any app.
    gates.record_version(str(output_dir), gates.REQUIREMENTS, svc.doc,
                         request=f"Made from the template “{src.get('name') or ''}”")
    if complete:
        gates.record_version(str(output_dir), gates.PRODUCT_MODEL, svc.doc)
    _mark(output_dir, status=MODE_EXACT, mode=MODE_EXACT, complete=complete, used_at=_now())
    from services.blueprint.orchestrator import DAG, completed_nodes
    done = completed_nodes(svc.doc)
    left = [k for k, n in DAG.items() if n.kind == "agent" and k not in done]
    return {"doc": svc.doc, "summary": summary(svc.doc), "complete": complete,
            "authoring_left": left}


def reference_document(doc: dict, *, name: str = "") -> str:
    """The template written out for the agents to work FROM, not copy.

    Evidence, in the same form as a document the person attaches: the agents
    cite it, and the person's own words about what is different win wherever
    the two disagree."""
    facts = summary(doc)
    lines = [f"# Reference application: {name or facts['name']}",
             "",
             "The person chose this existing application as the starting point and asked for "
             "something LIKE it. Keep what still fits; change what they said is different; "
             "where their words and this reference disagree, their words win.",
             "",
             f"Purpose: {facts['description']}"]
    reqs = _live(doc.get("requirements"))
    if reqs:
        lines += ["", "## What it does (requirements)"]
        lines += [f"- {r.get('description') or ''}" for r in reqs[:60]]
    entities = _live((doc.get("data") or {}).get("entities"))
    if entities:
        lines += ["", "## Records it keeps"]
        for e in entities[:40]:
            fields = ", ".join(str(f.get("name")) for f in (e.get("fields") or [])
                               if isinstance(f, dict))[:300]
            lines.append(f"- {e.get('name')}: {fields}" if fields else f"- {e.get('name')}")
    pages = _live(doc.get("pages"))
    if pages:
        lines += ["", "## Screens"]
        lines += [f"- {p.get('title') or p.get('route')} ({p.get('route')}): "
                  f"{(p.get('purpose') or '')[:160]}" for p in pages[:60]]
    workflows = _live(doc.get("workflows"))
    if workflows:
        lines += ["", "## Processes"]
        lines += [f"- {w.get('name')}" for w in workflows[:40]]
    roles = _live(doc.get("roles"))
    if roles:
        lines += ["", "## People who use it"]
        lines += [f"- {r.get('name')}: {(r.get('description') or '')[:160]}" for r in roles[:20]]
    return "\n".join(lines) + "\n"


def prepare_adapt(output_dir: str | Path, *, app_name: str = "", changes: str = "",
                  keep_look: bool = True) -> dict:
    """Start a NEW definition that works from the template.

    Returns ``brief`` (what to define from) and ``document`` (the template as
    reference evidence). With ``keep_look`` the template's design system is
    carried into the new definition, so the build keeps its colours, type and
    shape instead of designing new ones — and spends nothing doing so."""
    from services.blueprint.service import BlueprintService

    output_dir = Path(output_dir)
    src = source_of(output_dir) or {}
    tdoc = _staged_definition(output_dir)
    changes = str(changes or "").strip()
    if not changes:
        raise TemplateError("Say what should be different from the template — that is what "
                            "the new definition is written from.")
    tname = src.get("name") or summary(tdoc)["name"]
    brief = (f"{changes}\n\n(Start from the template “{tname}”: keep what still fits, "
             "change what is described above.)")
    current = output_dir / ".forge" / "blueprint" / "current.json"
    if current.is_file() and is_defined(BlueprintService.load(output_dir=output_dir).doc):
        raise TemplateError("This project already has a definition; a template can only "
                            "start a project, not replace one.")
    svc = BlueprintService.create(output_dir=output_dir, app_id=output_dir.name,
                                  name=(app_name or "Application").strip(), domain="unknown",
                                  description=brief)
    if keep_look and isinstance(tdoc.get("designSystem"), dict) and tdoc["designSystem"]:
        svc.doc["designSystem"] = json.loads(json.dumps(tdoc["designSystem"]))
        _copy_brand(output_dir)
        svc.validate()
        svc.save()
    document = {"name": f"Template — {tname}.md", "text": reference_document(tdoc, name=tname)}
    _mark(output_dir, status=MODE_ADAPT, mode=MODE_ADAPT, used_at=_now(),
          changes=changes[:2000], keep_look=bool(keep_look))
    return {"brief": brief, "document": document}


_SYNC_ENGINE = None


def project_facts(project_id: str) -> dict | None:
    """The project's organisation, owner and name — for a save made from
    inside a Smith turn, which runs on a worker thread with no database
    session of its own. Read-only; one short query."""
    global _SYNC_ENGINE
    try:
        uuid.UUID(str(project_id))
    except (ValueError, TypeError):
        return None
    try:
        from sqlalchemy import create_engine, text
        from config import DATABASE_URL_SYNC
        if _SYNC_ENGINE is None:
            _SYNC_ENGINE = create_engine(DATABASE_URL_SYNC, pool_pre_ping=True, pool_size=1,
                                         max_overflow=1)
        with _SYNC_ENGINE.connect() as conn:
            row = conn.execute(text(
                "SELECT p.org_id, p.owner_id, p.name, u.name AS owner_name "
                "FROM projects p LEFT JOIN platform_users u ON u.id = p.owner_id "
                "WHERE p.id = :pid"), {"pid": str(project_id)}).first()
    except Exception:  # noqa: BLE001 — a lookup that fails says so to the caller
        logger.exception("[templates] could not read project %s", project_id)
        return None
    if not row:
        return None
    return {"org_id": str(row[0]), "owner_id": str(row[1] or ""), "name": str(row[2] or ""),
            "owner_name": str(row[3] or "")}


def exact_build_pending(output_dir: str | Path) -> bool:
    """The project is an exact copy of a template that has not been built yet.

    Its build authors nothing: every agent's section came from the template, so
    running an agent could only spend money re-deciding what is already
    decided — and, for a page whose code the original never wrote, decide it
    differently from the application the person asked to copy."""
    src = source_of(output_dir)
    return bool(src and src.get("mode") == MODE_EXACT and src.get("status") == MODE_EXACT
                and src.get("complete", True))


def mark_built(output_dir: str | Path) -> None:
    if source_of(output_dir):
        _mark(output_dir, status=BUILT, built_at=_now())


__all__ = [
    "BUILT", "MODE_ADAPT", "MODE_EXACT", "PENDING", "PER_PROJECT_SECTIONS", "STAGE_DIR",
    "TemplateError", "counted", "delete", "exact_build_pending", "project_facts", "get", "is_defined",
    "is_modelled", "list_for_org",
    "load_definition", "mark_built", "pending", "prepare_adapt", "reference_document", "save",
    "snapshot", "source_of", "stage", "summary", "templates_root", "update", "use_exact",
]
