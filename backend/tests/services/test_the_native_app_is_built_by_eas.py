"""A native application is built from its OWN Expo project, and it is checked before an EAS build is queued.

The mobile-build runner built whatever sat in `<output>/mobile`: the old WebView shell. A native app (`mobile.native.enabled`)
has `<output>/native`. The runner now picks the folder by what the application is, makes the native project current from
the Blueprint, writes the web app's address INTO app.json (EAS's cloud builds do not receive this process's environment), makes
the Expo slug unique (one Expo account holds every application's project), says every reason a build cannot work before any EAS
time is spent, links an EAS project when there is none, and tells EAS the folder is not a git repository."""
from __future__ import annotations

import asyncio
import json
import types
from pathlib import Path

import pytest

from routers import mobile_builds as mb
from services import eas_client, native_build
from services.blueprint.native_projection import native_root, project_native

SCREEN = "export default function Screen() { return null; }"

DOC = {
    "application": {"name": "Iron Log"},
    "mobile": {"native": {"enabled": True}, "store": {"bundleId": "com.tentoro.ironlog"}},
    "designSystem": {"colors": {"primary": "hsl(75 100% 50%)"}},
    "roles": [{"id": "ROLE-001", "name": "User"}],
    "security": {},
    "data": {"entities": [{"id": "ENTITY-001", "name": "Workout", "fields": [{"name": "name", "type": "text"}]}]},
    "workflows": [],
    "pages": [
        {"id": "PAGE-001", "name": "Workouts", "route": "/workouts", "access": "authenticated"},
        {"id": "PAGE-002", "name": "Sign in", "route": "/login", "pattern": "auth", "auth": "login", "access": "public"},
    ],
    "nativeCode": [{"page": "PAGE-001", "screen": SCREEN}],
}
URL = "https://iron-log.example.app"


def prepared(tmp_path, doc=DOC, url=URL):
    out = tmp_path / "uaq6iu40"
    out.mkdir()
    native_build.prepare(out, doc, url)
    return out, native_root(out)


# ---- which folder -----------------------------------------------------------------------------------------------------

def test_a_native_app_builds_its_own_project(tmp_path):
    t = native_build.choose_target(tmp_path, DOC)
    assert (t.kind, t.dir) == ("native", native_root(tmp_path))


def test_any_other_app_builds_its_shell_when_it_has_one(tmp_path):
    (tmp_path / "mobile").mkdir()
    off = {**DOC, "mobile": {}}
    t = native_build.choose_target(tmp_path, off)
    assert (t.kind, t.dir) == ("shell", tmp_path / "mobile")
    assert native_build.choose_target(tmp_path, {}) is not None, "no Blueprint at all: the shell"


def test_an_app_with_neither_has_nothing_to_build(tmp_path):
    assert native_build.choose_target(tmp_path, {**DOC, "mobile": {}}) is None


# ---- prepared ---------------------------------------------------------------------------------------------------------

def test_the_web_apps_address_is_written_into_the_project(tmp_path):
    _, root = prepared(tmp_path, url=URL + "/")
    app = json.loads((root / "app.json").read_text("utf-8"))["expo"]
    assert app["extra"]["appUrl"] == URL, "EAS's cloud does not see an environment variable; the uploaded file carries it"


def test_the_slug_is_the_applications_own_and_the_same_every_time(tmp_path):
    out, root = prepared(tmp_path)
    slug = json.loads((root / "app.json").read_text("utf-8"))["expo"]["slug"]
    assert slug == "iron-log-uaq6iu40"
    native_build.prepare(out, DOC, URL)
    assert json.loads((root / "app.json").read_text("utf-8"))["expo"]["slug"] == slug
    assert native_build.unique_slug("iron-log", "ZZZ99999") != slug, "two applications named alike are two projects"
    assert native_build.unique_slug("iron-log-uaq6iu40", "uaq6iu40") == "iron-log-uaq6iu40"


def test_an_eas_project_already_linked_survives_being_prepared_again(tmp_path):
    out, root = prepared(tmp_path)
    data = json.loads((root / "app.json").read_text("utf-8"))
    data["expo"]["extra"]["eas"]["projectId"] = "abc-123"
    (root / "app.json").write_text(json.dumps(data), "utf-8")
    native_build.prepare(out, DOC, URL)
    assert native_build.project_id(root) == "abc-123"


def test_the_project_is_current_with_the_blueprint(tmp_path):
    out, root = prepared(tmp_path)
    changed = {**DOC, "application": {"name": "Iron Log Pro"}}
    native_build.prepare(out, changed, URL)
    assert json.loads((root / "app.json").read_text("utf-8"))["expo"]["name"] == "Iron Log Pro"


# ---- checked before it is queued ----------------------------------------------------------------------------------------

def check(root, doc=DOC, profile="preview", platform="android", url=URL):
    return native_build.preflight(root, doc, profile=profile, platform=platform, deployed_url=url)


def test_a_project_that_can_be_built_has_no_problems(tmp_path):
    _, root = prepared(tmp_path)
    for profile in ("preview", "production"):
        for platform in ("android", "ios"):
            assert check(root, profile=profile, platform=platform).problems == [], (profile, platform)


@pytest.mark.parametrize("url", ["http://iron-log.example.app", "https://localhost:3000", "https://10.0.2.2:6543",
                                 "http://127.0.0.1:6543", "", "iron-log.example.app"])
def test_an_address_a_phone_cannot_use_is_refused(tmp_path, url):
    _, root = prepared(tmp_path, url=url)
    problems = check(root, url=url).problems
    assert problems and ("address" in problems[0] or "Publish" in problems[0]), problems


def test_a_development_build_may_use_a_local_address(tmp_path):
    _, root = prepared(tmp_path, url="http://10.0.2.2:6543")
    assert check(root, profile="development", url="http://10.0.2.2:6543").problems == []


def test_a_bundle_id_the_stores_refuse_is_said(tmp_path):
    bad = {**DOC, "mobile": {"native": {"enabled": True}, "store": {"bundleId": "9lives"}}}
    _, root = prepared(tmp_path, doc=bad)
    assert any("bundle id" in p for p in check(root, doc=bad).problems)


def test_a_project_that_disagrees_with_the_blueprint_is_said(tmp_path):
    _, root = prepared(tmp_path)
    data = json.loads((root / "app.json").read_text("utf-8"))
    data["expo"]["ios"]["bundleIdentifier"] = "com.someone.else"
    (root / "app.json").write_text(json.dumps(data), "utf-8")
    assert any("does not match" in p for p in check(root, platform="ios").problems)
    assert check(root, platform="android").problems == [], "only the platform being built is held to it"


def test_a_missing_profile_icon_or_unfilled_placeholder_is_said(tmp_path):
    _, root = prepared(tmp_path)
    assert any('no "nightly" build profile' in p for p in check(root, profile="nightly").problems)
    icon = root / "assets" / "icon.png"
    icon.unlink()
    assert any("icon" in p and "missing" in p for p in check(root).problems)
    (root / "app.json").write_text((root / "app.json").read_text("utf-8").replace('"1.0.0"', '"__VERSION__"'), "utf-8")
    assert any("__VERSION__" in p for p in check(root).problems)


def test_the_eas_project_id_may_be_empty_before_the_link(tmp_path):
    _, root = prepared(tmp_path)
    assert native_build.project_id(root) == "", "nothing is linked yet: the link is the runner's first step"
    assert check(root).problems == []
    # and a placeholder left in that one place is read as "not linked", never as an id
    (root / "app.json").write_text((root / "app.json").read_text("utf-8").replace('"projectId": ""', '"projectId": "__EAS_PROJECT_ID__"'), "utf-8")
    assert native_build.project_id(root) == "" and check(root).problems == []


def test_no_project_yet_says_to_build_the_application(tmp_path):
    report = native_build.preflight(tmp_path / "native", DOC, profile="preview", platform="ios", deployed_url=URL)
    assert report.problems and "Build the application first" in report.problems[0]


def test_a_page_without_a_phone_screen_is_a_warning_not_a_stop(tmp_path):
    _, root = prepared(tmp_path, doc={**DOC, "nativeCode": []})
    report = check(root, doc={**DOC, "nativeCode": []})
    assert report.ok and any("Not on the phone yet" in w and "Workouts" in w for w in report.warnings)


# ---- linked to an EAS project ---------------------------------------------------------------------------------------------

def writes_id(root, value="proj-777", owner="tentoro"):
    """What `eas init` does: the project id AND the owning account go into app.json."""
    async def run(argv, cwd, env):
        run.calls.append((argv, cwd, env))
        data = json.loads((root / "app.json").read_text("utf-8"))
        data["expo"]["extra"]["eas"]["projectId"] = value
        if owner:
            data["expo"]["owner"] = owner
        (root / "app.json").write_text(json.dumps(data), "utf-8")
        return 0, "", ""
    run.calls = []
    return run


def test_an_unlinked_project_is_linked_once(tmp_path):
    _, root = prepared(tmp_path)
    run = writes_id(root)
    assert asyncio.run(native_build.ensure_eas_project(root, "tok", run=run)) == "proj-777"
    argv, cwd, env = run.calls[0]
    assert argv[:3] == ["npx", "eas-cli", "init"] and "--non-interactive" in argv and cwd == str(root)
    assert env["EXPO_TOKEN"] == "tok" and env["EAS_NO_VCS"] == "1"
    assert asyncio.run(native_build.ensure_eas_project(root, "tok", run=run)) == "proj-777"
    assert len(run.calls) == 1, "a linked project is not linked again"


def test_the_owning_account_survives_being_prepared_again(tmp_path):
    """A robot token is refused without `expo.owner` ("Owner of project ... must be specified in the owner field"). Projecting the
    phone project again rewrites app.json from the template, which has none: the second build always failed."""
    out, root = prepared(tmp_path)
    data = json.loads((root / "app.json").read_text("utf-8"))
    data["expo"]["owner"] = "tentoro"
    data["expo"]["extra"]["eas"]["projectId"] = "abc-123"
    (root / "app.json").write_text(json.dumps(data), "utf-8")
    native_build.prepare(out, DOC, URL)
    assert native_build.owner(root) == "tentoro" and native_build.project_id(root) == "abc-123"


def test_a_project_that_lost_its_owner_is_linked_again_to_the_same_project(tmp_path):
    _, root = prepared(tmp_path)
    data = json.loads((root / "app.json").read_text("utf-8"))
    data["expo"]["extra"]["eas"]["projectId"] = "abc-123"
    (root / "app.json").write_text(json.dumps(data), "utf-8")
    run = writes_id(root, value="abc-123")
    assert asyncio.run(native_build.ensure_eas_project(root, "tok", run=run)) == "abc-123"
    assert run.calls[0][0][-2:] == ["--id", "abc-123"], "the project that exists, never a second one"
    assert native_build.owner(root) == "tentoro"
    asyncio.run(native_build.ensure_eas_project(root, "tok", run=run))
    assert len(run.calls) == 1, "id and owner both there: nothing to link"


def test_a_link_that_wrote_no_owner_is_an_error(tmp_path):
    _, root = prepared(tmp_path)
    with pytest.raises(eas_client.EasClientError, match="no owner"):
        asyncio.run(native_build.ensure_eas_project(root, "tok", run=writes_id(root, owner="")))


def test_a_link_that_wrote_no_id_is_an_error(tmp_path):
    _, root = prepared(tmp_path)

    async def run(argv, cwd, env):
        return 0, "", ""

    with pytest.raises(eas_client.EasClientError, match="no project id"):
        asyncio.run(native_build.ensure_eas_project(root, "tok", run=run))


def test_a_refused_link_says_what_eas_said(tmp_path):
    _, root = prepared(tmp_path)

    async def run(argv, cwd, env):
        return 1, "", "Authentication failed"

    with pytest.raises(eas_client.EasClientError, match="Authentication failed"):
        asyncio.run(native_build.ensure_eas_project(root, "tok", run=run))


# ---- what EAS is told ---------------------------------------------------------------------------------------------------------

def test_eas_is_told_a_native_folder_has_no_git_repository_and_a_shell_is_not_changed(tmp_path):
    seen = []

    async def run(argv, cwd, env):
        seen.append(env)
        return 0, json.dumps([{"id": "b1", "status": "new"}]), ""

    asyncio.run(eas_client.create_build(str(tmp_path), profile="preview", platform="android", expo_token="t",
                                        deployed_url=URL, extra_env=eas_client.NO_VCS, run=run))
    asyncio.run(eas_client.create_build(str(tmp_path), profile="preview", platform="android", expo_token="t",
                                        deployed_url=URL, run=run))
    assert seen[0]["EAS_NO_VCS"] == "1" and "EAS_NO_VCS" not in seen[1]


def test_the_runner_links_and_builds_a_native_project_and_a_shell_the_same_way(tmp_path, monkeypatch):
    calls = []

    async def fake_link(root, token):
        calls.append(("link", str(root), token))
        return "p"

    async def fake_packages(root, **kw):
        calls.append(("packages", str(root)))
        return False

    async def fake_create(mobile_dir, **kw):
        calls.append(("create", mobile_dir, kw.get("extra_env")))
        return eas_client.BuildState(build_id="b1", status="finished")

    class Sess:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, model, key):
            return types.SimpleNamespace(status="completed")

    async def noop(*a, **k):
        return None

    monkeypatch.setattr(mb.native_build, "ensure_packages", fake_packages)
    monkeypatch.setattr(mb.native_build, "ensure_eas_project", fake_link)
    monkeypatch.setattr(mb, "create_build", fake_create)
    monkeypatch.setattr(mb, "_apply_state", noop)
    monkeypatch.setattr(mb, "async_session", lambda: Sess())
    creds = types.SimpleNamespace(expo_eas_token="tok", apple=None, google=None)
    monkeypatch.setattr(mb, "_apple_env", lambda c: {})
    monkeypatch.setattr(mb, "_google_env", lambda c: {})

    (tmp_path / "native").mkdir()
    (tmp_path / "native" / "app.json").write_text("{}", "utf-8")
    asyncio.run(mb._run_build_and_poll("row", str(tmp_path / "native"), "preview", "android", creds, URL, "native"))
    (tmp_path / "mobile").mkdir()
    (tmp_path / "mobile" / "app.json").write_text("{}", "utf-8")
    asyncio.run(mb._run_build_and_poll("row", str(tmp_path / "mobile"), "preview", "android", creds, URL))
    # The packages are installed BEFORE the link: Expo reads the app's plugins on this machine first.
    assert calls[0] == ("packages", str(tmp_path / "native"))
    assert calls[1] == ("link", str(tmp_path / "native"), "tok")
    assert calls[2][0] == "create" and calls[2][2] == eas_client.NO_VCS
    assert calls[2][1] != str(tmp_path / "native"), "EAS is run in a clean staged copy, not in the real folder"
    assert not Path(calls[2][1]).exists(), "and the copy is removed afterwards"
    # A PWA's WebView shell is an Expo project like any other: a robot token needs its owner, and EAS must not pack the
    # output folder, so it is linked and built from a staged copy too.
    assert calls[3] == ("packages", str(tmp_path / "mobile"))
    assert calls[4] == ("link", str(tmp_path / "mobile"), "tok")
    assert calls[5][0] == "create" and calls[5][2] == eas_client.NO_VCS and calls[5][1] != str(tmp_path / "mobile")
    assert not Path(calls[5][1]).exists()
    assert len(calls) == 6


# ---- the folder EAS is run in ------------------------------------------------------------------------------------------

def big_project(tmp_path):
    """A phone project the way it sits on a machine that has run it: installed packages, a prebuilt android/, secrets."""
    out = tmp_path / "uaq6iu40"
    out.mkdir()
    (out / "app").mkdir()
    (out / "app" / "web.txt").write_text("the web app, beside the phone project", "utf-8")
    root = out / "native"
    for rel, text in {
        "app.json": "{}", "eas.json": "{}", "package.json": "{}", ".easignore": "node_modules/",
        "app/_layout.tsx": "x", "src/theme.ts": "x", "assets/icon.png": "x",
        "node_modules/react/index.js": "x", "android/app/build.gradle": "x", "ios/Podfile": "x", ".expo/cache": "x",
        ".env": "SECRET=1", ".env.local": "SECRET=2", "secrets/ascApiKey.p8": "key", "release.jks": "key", "AuthKey.p8": "key",
    }.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, "utf-8")
    return out, root


def test_a_staged_copy_holds_the_phone_project_and_a_link_to_the_packages_and_nothing_else(tmp_path):
    out, root = big_project(tmp_path)
    staged = native_build.stage(root)
    try:
        # files that are really in the copy (the packages are a LINK, not copied: not counted, not uploaded)
        have = {p.relative_to(staged).as_posix() for p in staged.rglob("*")
                if p.is_file() and "node_modules" not in p.relative_to(staged).parts}
        assert have == {"app.json", "eas.json", "package.json", ".easignore", "app/_layout.tsx", "src/theme.ts", "assets/icon.png"}
        assert not (staged / "android").exists() and not (staged / "ios").exists()
    finally:
        native_build.unstage(staged)


def test_eas_can_read_the_installed_packages_through_a_link_that_is_not_a_copy(tmp_path):
    """EAS reads the app's config plugins on this machine before it uploads: `Failed to resolve plugin for module
    "expo-router" ... Do you have node modules installed?` was the whole reason the first staged build failed."""
    out, root = big_project(tmp_path)
    staged = native_build.stage(root)
    try:
        assert (staged / "node_modules" / "react" / "index.js").read_text("utf-8") == "x", "readable through the link"
        copied = sum(f.stat().st_size for f in staged.rglob("*") if f.is_file() and not (f.is_symlink()) and "node_modules" not in f.parts)
        assert copied < 5_000, "and it is a link: nothing was copied"
    finally:
        native_build.unstage(staged)


def test_removing_a_staged_copy_does_not_empty_the_real_packages(tmp_path):
    """A recursive delete that followed the link would have emptied the real node_modules (about a gigabyte)."""
    out, root = big_project(tmp_path)
    packages = root / "node_modules"
    staged = native_build.stage(root)
    native_build.unstage(staged)
    assert not staged.exists() and not staged.parent.exists()
    assert (packages / "react" / "index.js").read_text("utf-8") == "x", "the real packages are untouched"


def test_the_staged_copy_is_alone_so_eas_cannot_take_the_parent_as_its_project(tmp_path):
    """Run inside `output/<id>/native`, EAS (no git) took `output/<id>` as the root and packed the web app too: 230 MB."""
    out, root = big_project(tmp_path)
    staged = native_build.stage(root)
    try:
        assert out not in staged.parents and root not in staged.parents
        assert sorted(p.name for p in staged.parent.iterdir()) == ["project"], "nothing beside it"
    finally:
        native_build.unstage(staged)


def test_unstaging_removes_the_copy_and_never_touches_the_real_project(tmp_path):
    out, root = big_project(tmp_path)
    before = sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())
    staged = native_build.stage(root)
    native_build.unstage(staged)
    assert not staged.exists() and not staged.parent.exists()
    assert sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()) == before


def test_a_secret_is_never_staged_even_in_a_folder_we_did_not_expect(tmp_path):
    _, root = big_project(tmp_path)
    (root / "src" / "deep").mkdir()
    (root / "src" / "deep" / "private.p12").write_text("key", "utf-8")
    (root / "src" / "deep" / ".env.production").write_text("S=1", "utf-8")
    staged = native_build.stage(root)
    try:
        names = {p.name for p in staged.rglob("*") if p.is_file()}
        assert not names & {"private.p12", ".env.production", ".env", ".env.local", "AuthKey.p8", "ascApiKey.p8", "release.jks"}
    finally:
        native_build.unstage(staged)


def test_a_failed_link_fails_the_build_with_the_reason(tmp_path, monkeypatch):
    failed = []

    async def refuse(root, token):
        raise eas_client.EasClientError("eas init exited 1: Authentication failed")

    async def mark(row, message):
        failed.append(message)

    async def installed(root, **kw):
        return False

    monkeypatch.setattr(mb.native_build, "ensure_packages", installed)
    monkeypatch.setattr(mb.native_build, "ensure_eas_project", refuse)
    monkeypatch.setattr(mb, "_mark_failed", mark)
    creds = types.SimpleNamespace(expo_eas_token="tok", apple=None, google=None)
    asyncio.run(mb._run_build_and_poll("row", str(tmp_path), "preview", "ios", creds, URL, "native"))
    assert failed == ["eas init exited 1: Authentication failed"]


def test_the_template_keeps_a_prebuilt_native_folder_out_of_the_upload():
    from pathlib import Path
    text = (Path(__file__).resolve().parents[2] / "templates/native/.easignore").read_text("utf-8")
    for line in ("node_modules", "/android", "/ios", "*.p8", ".env"):
        assert line in text.splitlines(), line
