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

import contextlib
import json
import logging
import os
import re
import shutil
import threading
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

#: Screenshots a template may carry, and how big each may be. What a gallery
#: card and the reviewer look at; never the app's data.
SCREENSHOTS_DIR = "screenshots"
SCREENSHOT_MAX = 8
SCREENSHOT_BYTES_MAX = 5 * 1024 * 1024
#: Image kinds, told by their first bytes — never by the name or the type the
#: browser claims, either of which a person can set to anything.
_IMAGE_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", "png", "image/png"),
    (b"\xff\xd8\xff", "jpg", "image/jpeg"),
)
_SHOT_ID = re.compile(r"^[0-9a-f]{32}$")


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


#: What a Blueprint says when it does not know an app's domain — never a
#: category a person would pick or filter by.
_NO_DOMAIN = {"unknown", "other", "general", "none", "n/a"}


def clean_category(value: Any) -> str:
    text = str(value or "").strip()[:60]
    return "" if text.lower() in _NO_DOMAIN else text


def lineage_key(org_id: str, source_project_id: str, template_id: str) -> str:
    """What every version of one app's template shares: the organisation and
    the app it was taken from (a template with no source app is its own)."""
    return f"{org_id}:{source_project_id or template_id}"[:80]


def lineage_of(meta: dict) -> str:
    """A template's lineage — read from its meta, or worked out for one saved
    before versions existed."""
    return str(meta.get("lineage") or lineage_key(str(meta.get("org_id") or ""),
                                                  str(meta.get("source_project_id") or ""),
                                                  str(meta.get("id") or "")))


@contextlib.contextmanager
def _file_lock(path: Path):
    """One writer at a time, across processes (fcntl), or within this one
    where there is no fcntl (Windows, a development platform here)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import fcntl
    except ImportError:  # pragma: no cover - Windows
        fcntl = None  # type: ignore[assignment]
    if fcntl is None:
        with _THREAD_LOCKS_GUARD:
            lock = _THREAD_LOCKS.setdefault(str(path), threading.Lock())
        with lock:
            yield
        return
    with open(path, "a+") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


_THREAD_LOCKS: dict[str, threading.Lock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()


def _versions_file(lineage: str) -> Path:
    import hashlib
    return templates_root() / ".versions" / hashlib.sha1(lineage.encode()).hexdigest()


def _last_version(lineage: str) -> int:
    """The highest version this app's template has had — remembered past a
    deleted one, so a number shown once is never given to another."""
    try:
        return int(_versions_file(lineage).read_text().strip() or 0)
    except (OSError, ValueError):
        return 0


def _record_version(lineage: str, version: int) -> None:
    path = _versions_file(lineage)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(version))


def _root_lock():
    return _file_lock(templates_root() / ".save.lock")


def _meta_lock(template_id: str):
    """Held around every read-change-write of a template's meta.json, so two
    screenshots uploaded at once both land."""
    return _file_lock(_dir(template_id) / ".meta.lock")


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
        "pages": [str(p.get("title") or p.get("name") or p.get("route") or "") for p in pages][:16],
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
    lineage = lineage_key(str(org_id), str(source_project_id or ""), template_id)
    try:
        # The next version of this app's template is counted and written under
        # one lock, so two saves of the same app at once are v2 and v3, not two v2s.
        with _root_lock():
            version = 1 + max([_last_version(lineage)] +
                              [int(m.get("version") or 1) for m in list_for_org(str(org_id))
                               if lineage_of(m) == lineage])
            _record_version(lineage, version)
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
                "category": clean_category(category or facts["domain"]),
                "created_by": str(created_by or ""),
                "created_by_name": str(created_by_name or "")[:120],
                "source_project_id": str(source_project_id or ""),
                "source_short_id": output_dir.name,
                "source_version": int(doc.get("version") or 1),
                "lineage": lineage,
                "version": version,
                "screenshots": [],
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


def update(template_id: str, *, name: str | None = None, description: str | None = None,
           category: str | None = None) -> dict:
    if not get(template_id):
        raise TemplateError("That template does not exist.")
    with _meta_lock(template_id):
        meta = get(template_id)
        if not meta:
            raise TemplateError("That template does not exist.")
        if name is not None:
            if not str(name).strip():
                raise TemplateError("A template needs a name.")
            meta["name"] = str(name).strip()[:NAME_MAX]
        if description is not None:
            meta["description"] = str(description).strip()[:DESCRIPTION_MAX]
        if category is not None:
            meta["category"] = clean_category(category)
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
# Screenshots — what a reviewer and a gallery visitor look at
# --------------------------------------------------------------------------- #

def _image_kind(data: bytes) -> tuple[str, str] | None:
    """``(extension, media type)`` from the file's own first bytes, or None."""
    for magic, ext, media in _IMAGE_MAGIC:
        if data.startswith(magic):
            return ext, media
    if len(data) > 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp", "image/webp"
    return None


def _decoded_size(data: bytes) -> tuple[int, int]:
    """The picture's size, after decoding it in full: a file that only starts
    like an image, or one that unpacks to a vast bitmap, is refused here."""
    import io
    import warnings

    from PIL import Image

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as img:
                img.verify()
            with Image.open(io.BytesIO(data)) as img:
                img.load()
                return int(img.width), int(img.height)
    except (Image.DecompressionBombWarning, Image.DecompressionBombError):
        raise TemplateError("That picture is too large to show — use a normal screenshot.")
    except Exception:
        raise TemplateError("That file is not a picture Forge can read — use PNG, JPEG or WebP.")


def add_screenshot(template_id: str, data: bytes, *, caption: str = "",
                   source: str = "upload") -> dict:
    """Keep one screenshot with the template. Returns its entry in the meta."""
    if not get(template_id):
        raise TemplateError("That template does not exist.")
    if not data:
        raise TemplateError("That file is empty.")
    if len(data) > SCREENSHOT_BYTES_MAX:
        raise TemplateError(f"A screenshot can be at most {SCREENSHOT_BYTES_MAX // (1024 * 1024)} MB.")
    kind = _image_kind(data)
    if kind is None:
        raise TemplateError("Screenshots must be PNG, JPEG or WebP pictures.")
    width, height = _decoded_size(data)
    ext, media = kind
    shot = {"id": uuid.uuid4().hex, "ext": ext, "media_type": media, "width": width,
            "height": height, "caption": str(caption or "").strip()[:200],
            "source": source if source in ("upload", "app") else "upload", "added_at": _now()}
    with _meta_lock(template_id):
        meta = get(template_id) or {}
        shots = list(meta.get("screenshots") or [])
        if len(shots) >= SCREENSHOT_MAX:
            raise TemplateError(f"A template can show at most {SCREENSHOT_MAX} screenshots — "
                                "remove one first.")
        path = _dir(template_id) / SCREENSHOTS_DIR / f"{shot['id']}.{ext}"
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)
        meta["screenshots"] = shots + [shot]
        meta["updated_at"] = _now()
        _write_json(_dir(template_id) / "meta.json", meta)
    return shot


def remove_screenshot(template_id: str, shot_id: str) -> bool:
    if not _SHOT_ID.match(str(shot_id or "")) or not get(template_id):
        return False
    with _meta_lock(template_id):
        meta = get(template_id) or {}
        shots = list(meta.get("screenshots") or [])
        gone = [s for s in shots if s.get("id") == shot_id]
        if not gone:
            return False
        meta["screenshots"] = [s for s in shots if s.get("id") != shot_id]
        meta["updated_at"] = _now()
        _write_json(_dir(template_id) / "meta.json", meta)
    (_dir(template_id) / SCREENSHOTS_DIR / f"{shot_id}.{gone[0].get('ext')}").unlink(missing_ok=True)
    return True


def caption_screenshot(template_id: str, shot_id: str, caption: str) -> dict | None:
    """Say what one screenshot shows. None when there is no such picture."""
    if not _SHOT_ID.match(str(shot_id or "")) or not get(template_id):
        return None
    with _meta_lock(template_id):
        meta = get(template_id) or {}
        shots = list(meta.get("screenshots") or [])
        shot = next((s for s in shots if s.get("id") == shot_id), None)
        if shot is None:
            return None
        shot["caption"] = str(caption or "").strip()[:200]
        meta["screenshots"] = shots
        meta["updated_at"] = _now()
        _write_json(_dir(template_id) / "meta.json", meta)
    return shot


def order_screenshots(template_id: str, order: list[str]) -> list[dict]:
    """Put the screenshots in the given order; the first is the gallery cover.
    Ids not named keep their place after the named ones."""
    with _meta_lock(template_id):
        meta = get(template_id)
        if not meta:
            raise TemplateError("That template does not exist.")
        shots = list(meta.get("screenshots") or [])
        rank = {sid: i for i, sid in enumerate(order or [])}
        shots.sort(key=lambda s: rank.get(s.get("id"), len(rank)))
        meta["screenshots"] = shots
        meta["updated_at"] = _now()
        _write_json(_dir(template_id) / "meta.json", meta)
    return shots


def screenshot_file(template_id: str, shot_id: str) -> tuple[Path, str] | None:
    """The file and media type of one screenshot, or None. Named by id from
    the meta — nothing from the URL is joined into a path."""
    if not _SHOT_ID.match(str(shot_id or "")):
        return None
    meta = get(template_id)
    shot = next((s for s in (meta or {}).get("screenshots") or [] if s.get("id") == shot_id), None)
    if not shot or shot.get("ext") not in ("png", "jpg", "webp"):
        return None
    path = _dir(template_id) / SCREENSHOTS_DIR / f"{shot_id}.{shot['ext']}"
    return (path, str(shot.get("media_type") or "image/png")) if path.is_file() else None


def app_screens(output_dir: str | Path) -> list[tuple[str, Path]]:
    """The build's own picture of each page — ``(page name, file)``, the
    newest look of every page that has one, in the order of the app's pages."""
    output_dir = Path(output_dir)
    looks = output_dir / ".forge" / "look"
    if not looks.is_dir():
        return []
    names: dict[str, str] = {}
    order: list[str] = []
    current = output_dir / ".forge" / "blueprint" / "current.json"
    if current.is_file():
        try:
            doc = json.loads(current.read_text("utf-8"))
            for p in _live(doc.get("pages")):
                pid = str(p.get("id") or "")
                names[pid] = str(p.get("name") or p.get("title") or p.get("route") or pid)
                order.append(pid)
        except (OSError, ValueError):
            pass
    out = []
    for pid in order or sorted(d.name for d in looks.iterdir() if d.is_dir()):
        page_dir = looks / pid
        if not re.fullmatch(r"[A-Za-z0-9_-]+", pid) or not page_dir.is_dir():
            continue
        attempts = sorted((d for d in page_dir.iterdir() if d.is_dir() and d.name.startswith("look-")
                           and d.name[5:].isdigit()), key=lambda d: int(d.name[5:]))
        for attempt in reversed(attempts):
            shot = attempt / "desktop.png"
            if shot.is_file():
                out.append((names.get(pid, pid), shot))
                break
    return out


def add_app_screens(template_id: str, output_dir: str | Path) -> list[dict]:
    """Add the build's own page pictures, up to the limit. Pictures already
    added from the app (same caption) are not added twice."""
    meta = get(template_id)
    if not meta:
        raise TemplateError("That template does not exist.")
    have = {(s.get("source"), s.get("caption")) for s in meta.get("screenshots") or []}
    added = []
    for name, path in app_screens(output_dir):
        if len(meta.get("screenshots") or []) + len(added) >= SCREENSHOT_MAX:
            break
        if ("app", name[:200]) in have:
            continue
        try:
            added.append(add_screenshot(template_id, path.read_bytes(), caption=name, source="app"))
        except TemplateError as exc:
            logger.warning("[templates] skipped the picture of %s: %s", name, exc)
    return added


# --------------------------------------------------------------------------- #
# What the Gallery shows of a definition
# --------------------------------------------------------------------------- #

def preview(doc: dict) -> dict:
    """The definition as a visitor reads it: screens, records and their
    fields, processes and their steps, roles and rules — names and plain
    words, no ids to resolve on the other side."""
    roles = _live(doc.get("roles"))
    role_name = {str(r.get("id")): str(r.get("name") or "") for r in roles}
    entities = _live((doc.get("data") or {}).get("entities"))
    entity_name = {str(e.get("id")): str(e.get("name") or "") for e in entities}
    return {
        "screens": [{
            "name": str(p.get("name") or p.get("title") or p.get("route") or ""),
            "route": str(p.get("route") or ""),
            "purpose": str(p.get("purpose") or "")[:400],
            "who": [role_name[u] for u in (p.get("users") or []) if u in role_name],
        } for p in _live(doc.get("pages"))[:60]],
        "records": [{
            "name": str(e.get("name") or ""),
            "description": str(e.get("description") or "")[:300],
            "fields": [{
                "name": str(f.get("name") or ""),
                "type": str(f.get("type") or ""),
                "required": bool(f.get("required")),
                "description": str(f.get("description") or "")[:200],
                # A fixed list is part of what the record is: "one of travel, meals, office".
                "choices": [str(v) for v in (f.get("enumValues") or f.get("values") or f.get("enum") or [])
                            if not isinstance(v, (dict, list))][:30],
            } for f in (e.get("fields") or []) if isinstance(f, dict)][:60],
        } for e in entities[:40]],
        "workflows": [{
            "name": str(w.get("name") or ""),
            "purpose": str(w.get("purpose") or w.get("description") or "")[:400],
            "trigger": str(((w.get("trigger") or {}) if isinstance(w.get("trigger"), dict) else {})
                           .get("detail") or ""),
            "steps": [str(st.get("name") or st.get("key") or "") for st in (w.get("steps") or [])
                      if isinstance(st, dict)][:40],
        } for w in _live(doc.get("workflows"))[:40]],
        "roles": [{"name": str(r.get("name") or ""), "description": str(r.get("description") or "")[:300]}
                  for r in roles[:20]],
        "rules": [{"name": str(r.get("name") or ""), "statement": str(r.get("statement") or "")[:400],
                   "record": entity_name.get(str(r.get("entity") or ""), "")}
                  for r in _live(doc.get("businessRules"))[:60]],
    }


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
_SYNC_ENGINE_LOCK = threading.Lock()


def _sync_engine():
    """The one sync Engine this module reads through. Made once, under a lock:
    `project_facts` runs on Smith's worker threads, so two concurrent first
    calls would otherwise each build an Engine and leak all but one (with its
    pooled connections)."""
    global _SYNC_ENGINE
    if _SYNC_ENGINE is None:
        from sqlalchemy import create_engine

        from config import DATABASE_URL_SYNC
        with _SYNC_ENGINE_LOCK:
            if _SYNC_ENGINE is None:
                _SYNC_ENGINE = create_engine(DATABASE_URL_SYNC, pool_pre_ping=True,
                                             pool_size=1, max_overflow=1)
    return _SYNC_ENGINE


def project_facts(project_id: str) -> dict | None:
    """The project's organisation, owner and name — for a save made from
    inside a Smith turn, which runs on a worker thread with no database
    session of its own. Read-only; one short query."""
    try:
        uuid.UUID(str(project_id))
    except (ValueError, TypeError):
        return None
    try:
        from sqlalchemy import text
        with _sync_engine().connect() as conn:
            row = conn.execute(text(
                "SELECT p.org_id, p.owner_id, p.name, u.name AS owner_name "
                "FROM projects p LEFT JOIN platform_users u ON u.id = p.owner_id "
                "WHERE p.id = :pid"), {"pid": str(project_id)}).first()
    except Exception:
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
    "BUILT",
    "MODE_ADAPT",
    "MODE_EXACT",
    "PENDING",
    "PER_PROJECT_SECTIONS",
    "STAGE_DIR",
    "TemplateError",
    "add_app_screens",
    "add_screenshot",
    "app_screens",
    "caption_screenshot",
    "clean_category",
    "counted",
    "delete",
    "exact_build_pending",
    "get",
    "is_defined",
    "is_modelled",
    "lineage_key",
    "lineage_of",
    "list_for_org",
    "load_definition",
    "mark_built",
    "order_screenshots",
    "pending",
    "prepare_adapt",
    "preview",
    "project_facts",
    "reference_document",
    "remove_screenshot",
    "save",
    "screenshot_file",
    "snapshot",
    "source_of",
    "stage",
    "summary",
    "templates_root",
    "update",
    "use_exact",
]
