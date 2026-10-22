"""The editor's phone preview: the app's native screens, drawn in a browser tab, with sample data.

A native app's screens are React Native. A browser draws them through `react-native-web`, so the preview is the project's
own screens exported for the web, not a second copy of them. It is built in a COPY of the phone project (the project and
its EAS build are never touched) with three things added to the copy:

  * `src/sdk/preview.ts` and `preview-data.json`: the app's backend, in the page. Every request for the app's `/api/*` is
    answered as a signed-in sample person from rows made from the Blueprint's own entities, so nobody signs in and nothing
    real is read or written.
  * a Babel plugin that marks every element with the file and line that wrote it (`data-source-*`), which is what the
    editor's bridge reads to say what a person selected.
  * the web libraries (`react-native-web`, `react-dom`, `@expo/metro-runtime`), installed on first use.

The result is a static site under `.forge/phone-preview/dist`, served by `routers/phone_preview.py`.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time
import shutil
import stat
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

STATIC = Path(__file__).resolve().parent.parent / "static"
ASSETS = STATIC / "phone_preview"
WEB_PACKAGES = ("react-native-web", "react-dom", "@expo/metro-runtime")
SAMPLE_ROWS = 6
STEP_TIMEOUT = 900

_jobs: dict[str, asyncio.Task] = {}


class PhonePreviewError(Exception):
    """A sentence the editor shows, never a traceback."""


# --------------------------------------------------------------------------------------------------------------------
# Where things are
# --------------------------------------------------------------------------------------------------------------------

def work_dir(output_dir: str | Path) -> Path:
    return Path(output_dir) / ".forge" / "phone-preview"


def dist_dir(output_dir: str | Path) -> Path:
    return work_dir(output_dir) / "dist"


def serve_path(short_id: str) -> str:
    return f"/api/projects/{short_id}/phone/serve"


def native_dir(output_dir: str | Path) -> Path:
    from services.blueprint.native_projection import native_root
    return native_root(output_dir)


def native_enabled(output_dir: str | Path) -> bool:
    """The Blueprint says this app has React Native screens (`mobile.native.enabled`). A web or PWA app can still have a
    `native/` folder left from an earlier choice; it is not what the person is building, so it is not previewed."""
    try:
        doc = json.loads((Path(output_dir) / ".forge" / "blueprint" / "current.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    mobile = doc.get("mobile") if isinstance(doc.get("mobile"), dict) else {}
    native = mobile.get("native") if isinstance(mobile.get("native"), dict) else {}
    return native.get("enabled") is True


def has_screens(output_dir: str | Path) -> bool:
    root = native_dir(output_dir)
    return native_enabled(output_dir) and (root / "package.json").is_file() and (root / "app").is_dir()


def _fingerprint(output_dir: str | Path) -> str:
    """Changes when the phone screens or the Blueprint do: what says a built preview is out of date."""
    newest = 0.0
    root = native_dir(output_dir)
    for sub in ("app", "src"):
        for p in (root / sub).rglob("*"):
            if p.is_file():
                newest = max(newest, p.stat().st_mtime)
    # What the preview is drawn WITH counts too: a newer bridge (how the picture talks to the editor) is a picture to draw again.
    for extra in (root / "app.json", Path(output_dir) / ".forge" / "blueprint" / "current.json", STATIC / "bridge.js",
                  *(p for p in ASSETS.glob("*") if p.is_file())):
        if extra.is_file():
            newest = max(newest, extra.stat().st_mtime)
    return hashlib.sha1(str(newest).encode()).hexdigest()[:12]


# --------------------------------------------------------------------------------------------------------------------
# Status
# --------------------------------------------------------------------------------------------------------------------

def _status_path(output_dir: str | Path) -> Path:
    return work_dir(output_dir) / "status.json"


def _write_status(output_dir: str | Path, **fields: Any) -> dict:
    path = _status_path(output_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        current = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        current = {}
    current.update(fields)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(current), encoding="utf-8")
    os.replace(tmp, path)
    return current


def status(output_dir: str | Path, short_id: str) -> dict:
    """`state`: none | building | ready | failed | unavailable. `stale` is true when the screens changed after the build."""
    if not has_screens(output_dir):
        return {"state": "unavailable", "reason": "This app has no phone screens to preview.", "servePath": serve_path(short_id)}
    try:
        data = json.loads(_status_path(output_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    running = short_id in _jobs and not _jobs[short_id].done()
    state = "building" if running else data.get("state", "none")
    if state == "building" and not running:
        state = "failed"          # the server restarted mid-build
        data["error"] = data.get("error") or "The build was interrupted. Build it again."
    ready = (dist_dir(output_dir) / "index.html").is_file()
    if state == "ready" and not ready:
        state = "none"
    return {
        "state": state,
        "step": data.get("step", ""),
        "error": data.get("error", ""),
        "builtAt": data.get("builtAt"),
        "stale": bool(state == "ready" and data.get("fingerprint") != _fingerprint(output_dir)),
        "servePath": serve_path(short_id),
    }


# --------------------------------------------------------------------------------------------------------------------
# Sample data
# --------------------------------------------------------------------------------------------------------------------

_WORDS = ("Garden", "Harbor", "Maple", "Summit", "Cedar", "Willow", "Copper", "Meadow")
_CATEGORIES = ("General", "Home", "Work", "Personal", "Other")
_PEOPLE = ("Alex Rivera", "Sam Chen", "Jordan Patel", "Taylor Brooks", "Morgan Lee", "Casey Nguyen")
#: The columns of the account entity that hold a person's name.
_PERSON_NAME_FIELDS = ("name", "displayname", "fullname", "username")


def _iso(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sample_value(field: dict, entity: str, i: int, labels: str, person: bool = False) -> Any:
    from services.blueprint.app_sdk import _numeric, ts_type
    from services.blueprint.embeddings import is_file_field, is_image_field
    from services.blueprint.projection import base_type

    name = str(field.get("name") or "")
    low = name.lower()
    kind = base_type(field.get("type"))
    if is_image_field(field) or is_file_field(field):
        return None
    ts = ts_type(field)
    if ts == "boolean":
        return i % 3 != 2
    if ts == "string[]":
        return []
    if ts == "unknown":
        return None
    if ts.startswith('"'):
        options = re.findall(r'"((?:[^"\\]|\\.)*)"', ts)
        return options[i % len(options)] if options else None
    if _numeric(field):
        whole = kind in ("integer", "int", "smallint", "bigint")
        if any(w in low for w in ("price", "amount", "total", "cost", "balance")):
            return round(12.5 * (i + 1) + 4.0, 2)
        if any(w in low for w in ("rating", "score")):
            return 3 + (i % 3)
        return (i + 1) * 2 if whole else round((i + 1) * 2.5, 1)
    if "date" in kind or "time" in kind or low.endswith(("at", "date", "on")):
        return _iso((i - 1) * 3)
    if person and low in _PERSON_NAME_FIELDS:
        return _PEOPLE[i % len(_PEOPLE)]         # a person's name reads as one, not as "DisplayName 1"
    if "email" in low:
        return f"person{i + 1}@example.com"
    if "phone" in low:
        return f"+1 555 010{i}"
    if "url" in low or "link" in low or "website" in low:
        return "https://example.com"
    if low in ("name", "title", "label", labels):
        words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", entity).lower()
        return f"{words[:1].upper() + words[1:]} {i + 1}"
    if any(w in low for w in ("description", "note", "comment", "body", "summary")):
        return f"A short sample of the {low} for this {entity.lower()}."
    if any(w in low for w in ("categor", "type", "kind")):
        return _CATEGORIES[i % len(_CATEGORIES)]
    return f"{name[:1].upper() + name[1:]} {i + 1}"


def _points_at(column: str, ids: dict[str, list[str]]) -> Optional[str]:
    """The entity a column named like `userId` / `user_id` points at, when there is one of that name."""
    m = re.fullmatch(r"(.+?)(?:_id|Id)", column)
    if not m:
        return None
    want = re.sub(r"[^a-z0-9]", "", m.group(1).lower())
    return next((n for n in ids if re.sub(r"[^a-z0-9]", "", n.lower()) == want), None)


def sample_data(doc: dict) -> dict:
    """Rows for every entity, a signed-in sample person, and which entity is the account: `preview-data.json`."""
    from services.blueprint.account_model import account_entity
    from services.blueprint.app_sdk import _live, _numeric, entity_columns

    ents = _live((doc.get("data") or {}).get("entities"))
    by_id = {str(e.get("id")): e for e in ents}
    ids = {str(e.get("name")): [str(uuid.uuid5(uuid.NAMESPACE_URL, f"{e.get('name')}:{n}")) for n in range(SAMPLE_ROWS)] for e in ents}
    fks: dict[str, dict[str, str]] = {}
    for rel in (doc.get("data") or {}).get("relationships") or []:
        src, dst = by_id.get(str(rel.get("from"))), by_id.get(str(rel.get("to")))
        if src and dst and rel.get("fromField"):
            fks.setdefault(str(src.get("name")), {})[str(rel["fromField"])] = str(dst.get("name"))
    account = account_entity(doc)
    account_name = str(account.get("name")) if account else None
    person = {"id": str(uuid.uuid5(uuid.NAMESPACE_URL, "preview-user")), "name": "Preview User", "email": "preview@example.com",
              "role": "admin", "accountType": None, "activeOrgId": None, "orgRole": None}
    out: dict[str, Any] = {}
    for e in ents:
        name = str(e.get("name"))
        cols = entity_columns(e, doc)
        names = [str(f["name"]) for f in cols]
        label = e.get("labelField") or next((c for c in ("name", "title", "fullName", "label") if c in names), "")
        rows = []
        for i in range(SAMPLE_ROWS):
            row: dict[str, Any] = {}
            for f in cols:
                col = str(f["name"])
                if f.get("primaryKey") or col == "id":
                    row[col] = ids[name][i]
                elif col in fks.get(name, {}) or _points_at(col, ids):
                    target_name = fks.get(name, {}).get(col) or _points_at(col, ids)
                    target = ids.get(target_name) or [None]
                    # Whatever points at the account is the signed-in person's: a "my items" list is never empty.
                    row[col] = target[0] if target_name == account_name else target[i % len(target)]
                else:
                    row[col] = _sample_value(f, name, i, str(label), person=name == account_name)
            if name == account_name:
                if i == 0:
                    person["id"] = row.get("id", person["id"])
                if "email" in row:
                    row["email"] = person["email"] if i == 0 else f"person{i + 1}@example.com"
                if i == 0:
                    for col in row:
                        if col.lower() in _PERSON_NAME_FIELDS:
                            row[col] = person["name"]
            rows.append(row)
        out[name] = {"rows": rows, "label": label or "id", "numeric": [str(f["name"]) for f in cols if _numeric(f)]}
    return {"entities": out, "user": person, "account": account_name}


# --------------------------------------------------------------------------------------------------------------------
# The copy, and the build
# --------------------------------------------------------------------------------------------------------------------

_FETCH_LINE = "fetch: (url, init) => fetch(url, init),"
_BABEL = "\n".join([
    "module.exports = function (api) {",
    "  api.cache(true);",
    "  return {",
    '    presets: ["babel-preset-expo"],',
    '    plugins: [require("./forge-source-plugin.js")],',
    "  };",
    "};",
    "",
])


def _patch_api(staged: Path) -> None:
    """api.ts calls the page's own `fetch`; in the preview it calls the sample backend instead."""
    api = staged / "src" / "sdk" / "api.ts"
    text = api.read_text(encoding="utf-8")
    if _FETCH_LINE not in text:
        raise PhonePreviewError("The phone project's connection code has an unexpected shape, so it cannot be previewed.")
    text = text.replace(_FETCH_LINE, "fetch: (url, init) => previewFetch(url, init),", 1)
    anchor = 'import { signedOut } from "./events";'
    text = text.replace(anchor, anchor + chr(10) + 'import { previewFetch } from "./preview";', 1)
    api.write_text(text, encoding="utf-8", newline=chr(10))


def _prepare_copy(staged: Path, doc: dict, short_id: str) -> None:
    sdk = staged / "src" / "sdk"
    shutil.copyfile(ASSETS / "preview.ts", sdk / "preview.ts")
    (sdk / "preview-data.json").write_text(json.dumps(sample_data(doc)), encoding="utf-8")
    _patch_api(staged)
    shutil.copyfile(ASSETS / "forge-source-plugin.js", staged / "forge-source-plugin.js")
    (staged / "babel.config.js").write_text(_BABEL, encoding="utf-8", newline=chr(10))
    app = json.loads((staged / "app.json").read_text(encoding="utf-8"))
    expo = app.setdefault("expo", {})
    expo.setdefault("web", {})["bundler"] = "metro"
    expo.setdefault("experiments", {})["baseUrl"] = serve_path(short_id)
    # Any address: the sample backend answers every `/api/*` call before it leaves the page.
    expo.setdefault("extra", {})["appUrl"] = "http://preview.local"
    (staged / "app.json").write_text(json.dumps(app, indent=2), encoding="utf-8", newline=chr(10))


async def _run(cmd: list[str], cwd: Path, env: dict, what: str) -> str:
    exe = shutil.which(cmd[0]) or cmd[0]
    proc = await asyncio.create_subprocess_exec(
        exe, *cmd[1:], cwd=str(cwd), env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), STEP_TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        raise PhonePreviewError(f"{what} took too long and was stopped.")
    text = (out or b"").decode("utf-8", "replace")
    if proc.returncode != 0:
        tail = " ".join(text.strip().splitlines()[-3:])[:300]
        raise PhonePreviewError(f"{what} failed: {tail}")
    return text


def _inject_scripts(dist: Path, short_id: str) -> None:
    """Two scripts in the exported page: the editor's bridge (what a person hovers and selects) and the fit script (lets a
    screen's list scroll as it does on a phone). Absolute addresses: a screen reloaded at a deep route would resolve a
    relative one inside that route."""
    index = dist / "index.html"
    html = index.read_text(encoding="utf-8")
    tags = ""
    for name, source in (("__bridge.js", STATIC / "bridge.js"), ("__fit.js", ASSETS / "fit.js")):
        shutil.copyfile(source, dist / name)
        if name not in html:
            tags += f'<script src="{serve_path(short_id)}/{name}"></script>'
    if tags:
        html = html.replace("</body>", tags + "</body>", 1) if "</body>" in html else html + tags
        index.write_text(html, encoding="utf-8")


def _web_specs(modules: Path, missing: list[str]) -> list[str]:
    """`name@version` for each web library, at the version this project's Expo SDK is made for (its own table says which)."""
    try:
        table = json.loads((modules / "expo" / "bundledNativeModules.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        table = {}
    return [f"{name}@{table[name]}" if table.get(name) else name for name in missing]


def _stage_here(real: Path, target: Path) -> Path:
    """A clean copy of the phone project, in a folder that is THE SAME EVERY TIME.

    The bundler remembers what it did to each file, and some of what it remembers has the project's folder written into it:
    where the router looks for the app's screens. A new random folder for every redraw made the bundler reuse a memory that
    pointed at the previous, deleted one, and the preview drew "Error: No routes found" in 8 seconds, with none of the app in
    it (Cart Buddy, 2026-10-22). In one place every time, what it remembers is right, and a redraw only redoes what changed.

    The packages are a link to the project's own: it is taken away as a link, never deleted through."""
    from services import native_build

    if target.exists():
        native_build._unlink_packages(target / "node_modules")
        _rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(real, target, ignore=native_build._stage_ignore(real))
    native_build._link_packages(real / "node_modules", target / "node_modules")
    return target


def _packages_key(real: Path) -> str:
    """Changes when the phone project's dependencies do, so the shared packages are installed again only then."""
    h = hashlib.sha1()
    for name in ("package.json", "package-lock.json"):
        try:
            h.update((real / name).read_bytes())
        except OSError:
            pass
    h.update(",".join(WEB_PACKAGES).encode())
    return h.hexdigest()[:16]


async def _ensure_packages(output_dir: str, real: Path, staged: Path, env: dict) -> None:
    """The phone project's packages, there for the build in `staged`.

    A project that has them (an Expo build installed them) is used as it is. One that has none used to install them into
    the throwaway copy, so EVERY redraw spent about three minutes on `npm install`; they are now installed once into a
    folder kept beside the preview and linked into each copy, and installed again only when the dependencies change."""
    from services import native_build

    modules = real / "node_modules"
    if modules.is_dir():
        missing = [p for p in WEB_PACKAGES if not (modules / p).is_dir()]
        if missing:
            # ONCE, INTO THE PROJECT'S OWN PACKAGES. `expo install` ran in the throwaway copy and its install did not
            # reach the real folder, so every redraw added the web libraries again (about two minutes) and threw them away
            # (Cart Buddy, 2026-10-22). `--no-save` keeps the project's package.json as it is: the web libraries are for
            # the preview and are not something its Expo build needs.
            _write_status(output_dir, step="Adding the web libraries (the first time only)")
            await _run(["npm", "install", "--no-save", "--no-audit", "--no-fund", *_web_specs(modules, missing)], real, env,
                       "Adding the web libraries")
        return
    cache = work_dir(output_dir) / "packages"
    stamp = cache / ".key"
    key = _packages_key(real)
    kept = (cache / "node_modules").is_dir() and stamp.is_file() and stamp.read_text(encoding="utf-8").strip() == key
    if not kept:
        _write_status(output_dir, step="Installing the phone project's packages (the first time only)")
        _rmtree(cache)
        cache.mkdir(parents=True)
        for name in ("package.json", "package-lock.json", "app.json", ".npmrc"):
            source = staged / name if (staged / name).is_file() else real / name
            if source.is_file():
                shutil.copyfile(source, cache / name)
        await _run(["npm", "install", "--no-audit", "--no-fund"], cache, env, "Installing the packages")
        _write_status(output_dir, step="Adding the web libraries")
        await _run(["npx", "expo", "install", *WEB_PACKAGES], cache, env, "Adding the web libraries")
        stamp.write_text(key, encoding="utf-8")
    if not await asyncio.to_thread(native_build._link_packages, cache / "node_modules", staged / "node_modules"):
        raise PhonePreviewError("The kept packages could not be linked into the preview build.")


def _extended(path: Path) -> str:
    """The path in the form that goes past Windows' 260-character limit (the extended-length prefix); other systems have no such limit."""
    text = str(Path(path).resolve())
    if os.name == "nt" and not text.startswith("\\\\?\\"):
        return "\\\\?\\" + text
    return text


def _rmtree(path: Path) -> None:
    """Remove a folder, read-only files included. Never raises.

    The drawn picture holds copies of font files that come from the project's packages, and those are read-only: a plain
    `shutil.rmtree(..., ignore_errors=True)` skipped all 19 of them, left the folder behind, and the next swap was refused
    ("Access is denied") for as long as the leftover was there (Cart Buddy, 2026-10-22)."""
    def writable_then_retry(func, failed, _exc):
        try:
            os.chmod(failed, stat.S_IWRITE)
            func(failed)
        except OSError:
            pass

    if not Path(path).exists():
        return
    # The drawn picture keeps each font under the whole path it came from, which is longer than the 260 characters Windows
    # allows an ordinary path (280 here): the delete could not even find those files. The prefix lifts the limit.
    target = _extended(path)
    if sys.version_info >= (3, 12):
        shutil.rmtree(target, onexc=writable_then_retry)
    else:
        shutil.rmtree(target, onerror=lambda f, p, e: writable_then_retry(f, p, e))


def _swap(new: Path, final: Path) -> None:
    """Put the freshly drawn folder where the old one is, without ever leaving the preview without a folder.

    Windows refuses to move or delete a folder that has a file open, and the editor has the picture open while it loads
    (`WinError 5: Access is denied` after a good build, 2026-10-22). So the old folder is moved ASIDE, under a name of its
    own each time (a leftover of an earlier swap can then never be in the way), a busy one is tried again for a few seconds,
    and what is left of the old ones is removed when the new one is in."""
    for leftover in final.parent.glob(final.name + ".old*"):
        _rmtree(leftover)
    aside = final.with_name(f"{final.name}.old-{time.time_ns()}")
    last: OSError | None = None
    for attempt in range(8):
        try:
            if final.exists():
                os.replace(final, aside)
            os.replace(new, final)
            _rmtree(aside)
            return
        except OSError as exc:
            last = exc
            time.sleep(0.4 * (attempt + 1))
    # The new picture could not be put in place: put the old one back, and say so.
    try:
        if aside.exists() and not final.exists():
            os.replace(aside, final)
    except OSError:
        pass
    raise PhonePreviewError(f"The new picture could not be put in place ({last}). Try again in a moment.")


async def _build(output_dir: str, short_id: str) -> None:
    from services import native_build
    from services.blueprint.service import BlueprintService

    staged: Optional[Path] = None
    try:
        _write_status(output_dir, state="building", step="Preparing the screens", error="", fingerprint=_fingerprint(output_dir))
        doc = BlueprintService.load(output_dir=output_dir).doc
        real = native_dir(output_dir)
        stage_dir = work_dir(output_dir) / "stage"
        # The first build in a place starts the bundler's memory over: what it holds from other places (the random folders
        # of earlier redraws) points at folders that are gone.
        fresh = not stage_dir.exists()
        staged = await asyncio.to_thread(_stage_here, real, stage_dir)
        await asyncio.to_thread(_prepare_copy, staged, doc, short_id)
        env = {**os.environ, "CI": "1", "EXPO_NO_TELEMETRY": "1", "EXPO_NO_GIT_STATUS": "1"}
        await _ensure_packages(output_dir, real, staged, env)
        _write_status(output_dir, step="Drawing the screens")
        out = work_dir(output_dir) / "building"
        _rmtree(out)
        await _run(["npx", "expo", "export", "--platform", "web", "--output-dir", str(out), *(["--clear"] if fresh else [])],
                   staged, env, "Drawing the screens")
        if not (out / "index.html").is_file():
            raise PhonePreviewError("The export finished but produced no page.")
        _inject_scripts(out, short_id)
        final = dist_dir(output_dir)
        _swap(out, final)
        _write_status(output_dir, state="ready", step="", error="", builtAt=datetime.now(timezone.utc).isoformat())
    except PhonePreviewError as exc:
        _write_status(output_dir, state="failed", step="", error=str(exc))
    except Exception as exc:  # noqa: BLE001 - said as a reason, not a traceback
        logger.exception("phone preview build failed for %s", short_id)
        _write_status(output_dir, state="failed", step="", error=f"The preview could not be built ({type(exc).__name__}: {str(exc)[:160]}).")
    # The copy is kept: the next redraw is made in the same place (see `_stage_here`).


def start(output_dir: str | Path, short_id: str) -> dict:
    """Begin a build in the background (one at a time per project) and say where it stands."""
    if not has_screens(output_dir):
        raise PhonePreviewError("This app has no phone screens to preview.")
    job = _jobs.get(short_id)
    if job is None or job.done():
        _write_status(output_dir, state="building", step="Starting", error="")
        _jobs[short_id] = asyncio.create_task(_build(str(output_dir), short_id))
    return status(output_dir, short_id)
