"""The native app's EAS build: what is built, whether it can be built, and what EAS is told.

The mobile-build runner built whatever was in `<output>/mobile` (the old WebView shell). A native application
(`mobile.native.enabled`) has its own Expo project in `<output>/native`, so the runner asks here:

  * `choose_target`  which folder is built, and of which kind (the native project, or the shell of an app that has one);
  * `prepare`        the native project made current from the Blueprint, with the address of the web app written INTO
                     `app.json` and an Expo slug no other application shares;
  * `preflight`      every reason the build cannot work, said in plain words BEFORE any EAS time is spent;
  * `ensure_eas_project`  the folder linked to an EAS project (the shell expected somebody to run `eas init` by hand).

WHY THE ADDRESS IS WRITTEN INTO app.json: EAS builds in its own cloud and does not receive this process's environment, so
`EXPO_PUBLIC_APP_URL` set on the CLI reached nobody. `extra.appUrl` travels in the uploaded project, and the app reads it
(`src/sdk/api.ts`).

WHY THE SLUG HAS THE PROJECT'S ID IN IT: every application's EAS project is made under one Expo account, and a slug is
unique there. Two organisations each calling an app "Leafy" would otherwise be one project, or an error.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

#: com.acme.app: dot-separated, each part starting with a letter (the stores' rule, and the Blueprint contract's).
BUNDLE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+$")
#: Addresses that mean "this machine": an installed app cannot reach them.
LOCAL_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0", "10.0.2.2", "[::1]")
#: What the template leaves for a later step: the EAS project id (written by `eas init`) is allowed to be empty.
_PLACEHOLDER = re.compile(r"__[A-Z][A-Z0-9_]*__")


class NativeBuildError(RuntimeError):
    """The native project could not be got ready to build; the message says why."""


@dataclass(frozen=True)
class Target:
    kind: str                     # "native" | "shell"
    dir: Path


@dataclass
class Report:
    """What the preflight found. `problems` stop the build; `warnings` are said and do not."""
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def choose_target(output_dir: str | Path, doc: Optional[dict]) -> Optional[Target]:
    """The folder to build. A native application builds its own project; any other the shell, when it has one."""
    from services.blueprint.native_projection import enabled, native_root

    if doc and enabled(doc):
        return Target("native", native_root(output_dir))
    shell = Path(output_dir) / "mobile"
    return Target("shell", shell) if shell.is_dir() else None


def _read_app_json(native_dir: Path) -> dict:
    try:
        return json.loads((native_dir / "app.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise NativeBuildError(f"the phone project's app.json cannot be read ({exc})") from exc


def _write_app_json(native_dir: Path, data: dict) -> None:
    (native_dir / "app.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def unique_slug(base: str, short_id: str) -> str:
    """`<name>-<project id>`: the same every time for one project, never the same for two."""
    tail = re.sub(r"[^a-z0-9]", "", str(short_id).lower())
    base = re.sub(r"[^a-z0-9-]+", "-", str(base or "app").lower()).strip("-") or "app"
    return base if (tail and base.endswith("-" + tail)) else f"{base}-{tail}" if tail else base


def prepare(output_dir: str | Path, doc: dict, deployed_url: str) -> Path:
    """The native project, current: projected from the Blueprint, the web app's address and a unique slug written in.

    Projecting is deterministic (no model), keeps an EAS project id already linked, and is what a Smith edit or a build
    would have written; doing it here means a build never ships a project older than the Blueprint."""
    from services.blueprint.native_projection import native_root, project_native

    try:
        project_native(doc, output_dir)
    except Exception as exc:  # noqa: BLE001 - said as a reason, not a traceback
        raise NativeBuildError(f"the phone project could not be written from the Blueprint ({type(exc).__name__}: {str(exc)[:160]})") from exc
    root = native_root(output_dir)
    data = _read_app_json(root)
    expo = data.setdefault("expo", {})
    extra = expo.setdefault("extra", {})
    extra["appUrl"] = str(deployed_url or "").strip().rstrip("/")
    expo["slug"] = unique_slug(str(expo.get("slug") or "app"), Path(output_dir).name)
    _write_app_json(root, data)
    return root


def _host(url: str) -> str:
    m = re.match(r"^[a-z][a-z0-9+.-]*://([^/:?#]+|\[[^\]]+\])", url.strip(), re.I)
    return (m.group(1) if m else "").lower()


def preflight(native_dir: Path, doc: dict, *, profile: str, platform: str, deployed_url: str) -> Report:
    """Every reason this build cannot work, found before it is queued."""
    from services.blueprint.native_projection import bundle_id, screen_gaps

    report = Report()
    if not (native_dir / "app.json").is_file() or not (native_dir / "package.json").is_file():
        report.problems.append("The phone project has not been written yet. Build the application first.")
        return report
    try:
        expo = _read_app_json(native_dir).get("expo") or {}
    except NativeBuildError as exc:
        report.problems.append(str(exc))
        return report

    # The id the stores know the app by: valid, and the same in the Blueprint, app.json's iOS and Android entries.
    wanted = bundle_id(doc)
    ios_id = str((expo.get("ios") or {}).get("bundleIdentifier") or "")
    android_id = str((expo.get("android") or {}).get("package") or "")
    if not BUNDLE.match(wanted):
        report.problems.append(f"The bundle id \"{wanted}\" is not one the app stores accept "
                               "(dot-separated parts, each starting with a letter, like com.acme.app). Change it in the app's mobile settings.")
    elif platform == "ios" and ios_id != wanted or platform == "android" and android_id != wanted:
        report.problems.append("The phone project's bundle id does not match the Blueprint's. Rebuild the phone project.")

    # Where the web app is: an installed app cannot reach this machine, and the stores refuse plain http.
    host = _host(deployed_url)
    if not host:
        report.problems.append("The web app has no address yet. Publish it first: the phone app talks to it.")
    elif profile != "development":
        if host in LOCAL_HOSTS or host.endswith(".local") or host.endswith(".localhost"):
            report.problems.append(f"The web app's address ({deployed_url}) is on this machine: an installed phone app cannot reach it. Publish the web app first.")
        elif not deployed_url.strip().lower().startswith("https://"):
            report.problems.append(f"The web app's address ({deployed_url}) is not https. iPhones and Android phones refuse a plain-http server in a store build.")

    # The build profile, and the artwork the stores and the home screen need.
    try:
        eas = json.loads((native_dir / "eas.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        eas = None
    if eas is None:
        report.problems.append("The phone project has no eas.json, so it has no build profiles. Rebuild the phone project.")
    elif profile not in (eas.get("build") or {}):
        report.problems.append(f"The phone project has no \"{profile}\" build profile.")
    for label, rel in (("icon", expo.get("icon")), ("splash image", ((expo.get("splash") or {}).get("image"))),
                       ("Android adaptive icon", ((expo.get("android") or {}).get("adaptiveIcon") or {}).get("foregroundImage"))):
        if rel and not (native_dir / str(rel)).is_file():
            report.problems.append(f"The app's {label} ({rel}) is missing from the phone project. Rebuild the phone project.")

    # A placeholder the template leaves is for a step that did not run. The EAS project id is the one allowed to be empty.
    for name in ("app.json", "eas.json"):
        try:
            text = (native_dir / name).read_text(encoding="utf-8")
        except OSError:
            continue
        left = sorted({m for m in _PLACEHOLDER.findall(text) if m != "__EAS_PROJECT_ID__"})
        if left:
            report.problems.append(f"{name} still holds the unfilled placeholder {', '.join(left)}. Rebuild the phone project.")

    gaps = screen_gaps(doc)
    if gaps:
        names = ", ".join(str(p.get("name") or p.get("route")) for p in gaps[:5])
        report.warnings.append(f"{len(gaps)} page{'s' if len(gaps) != 1 else ''} ({names}) will open as \"Not on the phone yet\" in this build.")
    return report


def project_id(native_dir: Path) -> str:
    """The EAS project id in app.json, or "" when there is none (or the template's placeholder)."""
    try:
        value = str((((_read_app_json(native_dir).get("expo") or {}).get("extra") or {}).get("eas") or {}).get("projectId") or "")
    except NativeBuildError:
        return ""
    return "" if value.startswith("__") else value.strip()


async def ensure_eas_project(native_dir: Path, expo_token: str, *, run: Any = None) -> str:
    """The folder linked to an EAS project, linking it when it is not: `eas init`, which writes the id into app.json.

    Returns the project id. The id is kept by every later projection, so this runs once per application."""
    from services.eas_client import EasClientError, link_project

    have = project_id(native_dir)
    if have:
        return have
    await link_project(str(native_dir), expo_token=expo_token, **({"run": run} if run else {}))
    linked = project_id(native_dir)
    if not linked:
        raise EasClientError("eas init finished but wrote no project id into app.json")
    return linked


__all__ = ["BUNDLE", "LOCAL_HOSTS", "NativeBuildError", "Report", "Target", "choose_target", "ensure_eas_project",
           "prepare", "preflight", "project_id", "unique_slug"]
