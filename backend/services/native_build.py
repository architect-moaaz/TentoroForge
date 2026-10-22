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

import asyncio
import json
import os
import re
import shutil
import subprocess
import tempfile
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
    if shell.is_dir():
        return Target("shell", shell)
    # A PWA's phone app is the shell, and `prepare_shell` makes it when there is none yet (full generation makes it;
    # an app built another way, or before this choice, does not).
    surface = str(((doc or {}).get("mobile") or {}).get("surface") or "") if doc else ""
    return Target("shell", shell) if surface in SHELL_SURFACES else None


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

    # THE EXPO ACCOUNT THAT OWNS THE PROJECT IS KEPT. `eas init` writes `expo.owner`, and a robot access token is refused
    # without it ("Owner of project ... must be specified in the owner field when using a robot access token"). Projecting
    # the phone project again rewrites app.json from the template, which has no owner: the second build always failed.
    try:
        prior_owner = str(((_read_app_json(native_root(output_dir)).get("expo") or {}).get("owner")) or "").strip()
    except NativeBuildError:
        prior_owner = ""
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
    if prior_owner:
        expo["owner"] = prior_owner
    _write_app_json(root, data)
    return root


#: The choices whose phone app is the WebView shell: it opens the installable website inside an app.
SHELL_SURFACES = ("web_pwa", "pwa_only")


def _brand_hex(doc: dict) -> str:
    value = str((((doc or {}).get("designSystem") or {}).get("colors") or {}).get("primary") or "").strip()
    return value if re.match(r"^#[0-9a-fA-F]{6}$", value) else ""


#: What in an application's pages means it uses the phone's camera: a barcode scanner, a photo capture, an image search, or
#: a page of the `capture` pattern.
_CAMERA_USE = re.compile(r"BarcodeScanner|CameraCapture|ImageSearch|\"pattern\":\s*\"capture\"")


def uses_camera(doc: dict) -> bool:
    """Does the application use the camera? Decided from its own pages, so a habit tracker does not ask for it."""
    text = json.dumps([doc.get("pageCode"), doc.get("pageLayouts"), doc.get("pages")], ensure_ascii=False, default=str)
    return bool(_CAMERA_USE.search(text))


def prepare_shell(output_dir: str | Path, doc: dict, deployed_url: str) -> Path:
    """The WebView shell of a PWA, current: made when the application has none, with the web app's address, its brand
    colour and icons, and a unique slug written in. Keeps the EAS project and the owning Expo account already linked
    (the scaffold rewrites app.json from the template, and a robot token is refused without the owner)."""
    from services.mobile_branding import apply_mobile_branding
    from services.mobile_scaffold import scaffold_mobile

    out = Path(output_dir)
    shell = out / "mobile"
    try:
        prior_owner = str(((_read_app_json(shell).get("expo") or {}).get("owner")) or "").strip()
    except NativeBuildError:
        prior_owner = ""
    name = str((doc.get("application") or {}).get("name") or "").strip() or None
    bundle = str((((doc.get("mobile") or {}).get("store")) or {}).get("bundleId") or "").strip() or None
    try:
        scaffold_mobile(str(out), app_name=name, deployed_url=str(deployed_url or "").strip().rstrip("/"),
                        brand_hex=_brand_hex(doc) or None, bundle_id=bundle)
        apply_mobile_branding(str(shell))
    except Exception as exc:  # noqa: BLE001 - said as a reason, not a traceback
        raise NativeBuildError(f"the phone app could not be written ({type(exc).__name__}: {str(exc)[:160]})") from exc
    data = _read_app_json(shell)
    expo = data.setdefault("expo", {})
    expo["slug"] = unique_slug(str(expo.get("slug") or "app"), out.name)
    expo["scheme"] = expo["slug"]
    # THE CAMERA ONLY WHEN THE APP USES IT: the shell's Scan button, its start-up camera prompt and the manifest's camera,
    # microphone and storage permissions are for apps with a scanner. Without one they are a prompt people refuse and a
    # question in store review.
    camera = uses_camera(doc)
    expo.setdefault("extra", {})["camera"] = camera
    if not camera:
        # `permissions: []` is not enough: the camera library brings its own into the manifest. Expo's `blockedPermissions`
        # removes them from the built app.
        expo.setdefault("android", {})["permissions"] = []
        expo["android"]["blockedPermissions"] = [
            "android.permission.CAMERA", "android.permission.RECORD_AUDIO",
            "android.permission.READ_EXTERNAL_STORAGE", "android.permission.WRITE_EXTERNAL_STORAGE",
        ]
        plist = (expo.get("ios") or {}).get("infoPlist") or {}
        for key in ("NSCameraUsageDescription", "NSMicrophoneUsageDescription", "NSPhotoLibraryUsageDescription"):
            plist.pop(key, None)
    if prior_owner:
        expo["owner"] = prior_owner
    _write_app_json(shell, data)
    return shell


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


def owner(native_dir: Path) -> str:
    """The Expo account that owns the linked project (`expo.owner`), or "" when app.json does not name one."""
    try:
        return str((_read_app_json(native_dir).get("expo") or {}).get("owner") or "").strip()
    except NativeBuildError:
        return ""


#: What a build never carries: installed packages (EAS installs its own), a native project made on somebody's machine (it
#: would turn this managed project into a bare one), local caches, and every kind of secret.
_STAGE_SKIP_DIRS = {"node_modules", "android", "ios", ".expo", "dist", "web-build", ".git", "__tests__"}
_STAGE_SKIP_SUFFIXES = (".jks", ".p8", ".p12", ".key", ".mobileprovision")


def _stage_ignore(source: Path):
    def ignore(directory: str, names: list[str]) -> set[str]:
        skipped = set()
        for name in names:
            if Path(directory) == source and name in _STAGE_SKIP_DIRS:
                skipped.add(name)
            elif name == "secrets" or name == ".env" or name.startswith(".env.") or name.endswith(_STAGE_SKIP_SUFFIXES):
                skipped.add(name)
        return skipped

    return ignore


def stage(native_dir: Path) -> Path:
    """A clean copy of the phone project, alone in a temporary folder: what EAS is run in and what it uploads.

    WITHOUT THIS EAS PACKED THE WHOLE OUTPUT FOLDER. `output/<id>/native` is not a git repository and sits beside `app/`
    (the web app) and `.forge/`; with no git, EAS took the PARENT as the project root and archived all of it: a 230 MB
    upload of the web app, a prebuilt `android/` folder and everything else, ten minutes of it, and our `.easignore` (one
    level down) was never read. Alone in its own folder, the project is the root, and the upload is a few megabytes."""
    native_dir = Path(native_dir)
    root = Path(tempfile.mkdtemp(prefix="forge-eas-"))
    staged = root / "project"
    shutil.copytree(native_dir, staged, ignore=_stage_ignore(native_dir))
    _link_packages(native_dir / "node_modules", staged / "node_modules")
    return staged


def _link_packages(target: Path, link: Path) -> bool:
    """Let the staged copy READ the installed packages without copying them (a gigabyte).

    EAS reads the app's config plugins on this machine before it uploads anything (`Failed to resolve plugin for module
    "expo-router" ... Do you have node modules installed?`), so the staged project needs `node_modules` to be there. It is
    a link, and `.easignore` skips it: nothing in it is uploaded. A junction on Windows (no privilege needed), a symlink
    elsewhere. False when it could not be made (the build then says what EAS said)."""
    if not target.is_dir():
        return False
    try:
        if os.name == "nt":
            done = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, timeout=30)
            return done.returncode == 0 and link.exists()
        os.symlink(target, link, target_is_directory=True)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def _unlink_packages(link: Path) -> None:
    """Remove the link and ONLY the link: a recursive delete that followed it would empty the real node_modules."""
    try:
        if link.is_symlink():
            link.unlink()
        elif os.name == "nt" and link.exists():
            os.rmdir(link)                 # a junction: removes the junction, never what it points at
    except OSError:
        pass


def unstage(staged: Path) -> None:
    """Remove a staged copy (and the temporary folder it lives in). Never touches the real project or its packages."""
    staged = Path(staged)
    _unlink_packages(staged / "node_modules")
    shutil.rmtree(staged.parent if staged.name == "project" else staged, ignore_errors=True)


def write_submit_keys(staged: Path, platform: str, *, google_json: str = "", apple: Any = None) -> None:
    """Put the store keys INTO THE STAGED COPY and point the `submit` profile at them: a non-interactive `eas submit` takes
    its keys from files named in eas.json, not from the environment. They exist only in the staged folder, which
    `unstage` deletes; the project's own eas.json never names a key."""
    staged = Path(staged)
    path = staged / "eas.json"
    config = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    profile = config.setdefault("submit", {}).setdefault("production", {})
    if platform == "android":
        if not google_json:
            raise NativeBuildError("There is no Google Play service-account key to submit with.")
        (staged / "play-key.json").write_text(google_json, encoding="utf-8")
        profile["android"] = {**(profile.get("android") or {}), "serviceAccountKeyPath": "./play-key.json"}
    else:
        wanted = {"key_id": "APPLE_ASC_KEY_ID", "issuer_id": "APPLE_ASC_ISSUER_ID", "private_key": "APPLE_ASC_PRIVATE_KEY",
                  "team_id": "APPLE_TEAM_ID", "app_id": "APPLE_ASC_APP_ID"}
        missing = [name for field_name, name in wanted.items() if not getattr(apple, field_name, None)]
        if missing:
            raise NativeBuildError("An App Store submit needs " + ", ".join(missing) + " in Settings → Integrations.")
        (staged / "asc-key.p8").write_text(apple.private_key, encoding="utf-8")
        profile["ios"] = {**(profile.get("ios") or {}), "ascApiKeyPath": "./asc-key.p8", "ascApiKeyId": apple.key_id,
                          "ascApiKeyIssuerId": apple.issuer_id, "appleTeamId": apple.team_id, "ascAppId": str(apple.app_id)}
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")


def project_id(native_dir: Path) -> str:
    """The EAS project id in app.json, or "" when there is none (or the template's placeholder)."""
    try:
        value = str((((_read_app_json(native_dir).get("expo") or {}).get("extra") or {}).get("eas") or {}).get("projectId") or "")
    except NativeBuildError:
        return ""
    return "" if value.startswith("__") else value.strip()


async def _npm_run(argv: list[str], cwd: str, timeout: float) -> tuple[int, str]:
    """`npm` as a subprocess: its return code and the end of what it said. (`npm` is `npm.cmd` on Windows; a bare name
    is not found there.)"""
    exe = shutil.which(argv[0]) or argv[0]
    proc = await asyncio.create_subprocess_exec(
        exe, *argv[1:], cwd=cwd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 124, f"npm took longer than {int(timeout // 60)} minutes and was stopped"
    return proc.returncode or 0, (out or b"").decode("utf-8", "replace")[-700:]


async def ensure_packages(native_dir: Path, *, run: Any = None, timeout: float = 1500.0) -> bool:
    """The phone project's packages, installed once, so Expo can read the app's config plugins on this machine.

    `eas init` and `eas build` resolve plugins such as `expo-router` BEFORE anything is uploaded, and failed with "Failed to
    resolve plugin for module expo-router ... Do you have node modules installed?" for any phone app whose packages nobody
    had installed (the web app's `install` node installs the web app's, and the type-check toolchain is its own folder).
    True when it had to install; False when they were there already."""
    native_dir = Path(native_dir)
    if (native_dir / "node_modules" / "expo").is_dir():
        return False
    if not (native_dir / "package.json").is_file():
        raise NativeBuildError("the phone project has no package.json, so its packages cannot be installed")
    run = run or _npm_run
    rc, said = await run(["npm", "install", "--no-audit", "--no-fund"], str(native_dir), timeout)
    if rc != 0:
        raise NativeBuildError(f"installing the phone project's packages failed (npm exited {rc}): {said.strip()[-400:]}")
    if not (native_dir / "node_modules" / "expo").is_dir():
        raise NativeBuildError("the phone project's packages were installed but `expo` is not among them")
    return True


async def ensure_eas_project(native_dir: Path, expo_token: str, *, run: Any = None) -> str:
    """The folder linked to an EAS project, linking it when it is not: `eas init`, which writes the id AND the owning
    account into app.json. A robot token is refused without the owner, so a project that has its id but lost its owner
    is linked again (to the SAME project: `--id`), which writes the owner back.

    Returns the project id. Both are kept by every later projection, so this runs once per application."""
    from services.eas_client import EasClientError, link_project

    have = project_id(native_dir)
    if have and owner(native_dir):
        return have
    await link_project(str(native_dir), expo_token=expo_token, project_id=have, **({"run": run} if run else {}))
    linked = project_id(native_dir)
    if not linked:
        raise EasClientError("eas init finished but wrote no project id into app.json")
    if not owner(native_dir):
        raise EasClientError("eas init finished but wrote no owner into app.json, and a robot token needs one")
    return linked


__all__ = ["BUNDLE", "LOCAL_HOSTS", "SHELL_SURFACES", "NativeBuildError", "Report", "Target", "choose_target", "ensure_eas_project", "ensure_packages",
           "owner", "prepare", "prepare_shell", "preflight", "project_id", "stage", "unique_slug", "unstage", "uses_camera", "write_submit_keys"]
