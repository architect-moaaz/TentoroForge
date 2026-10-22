"""The phone preview installs the project's packages once, not on every redraw.

An app whose phone project has no `node_modules` installed its packages into the throwaway copy it builds in: about three
minutes of `npm install`, thrown away, on every redraw. They are now installed into a folder kept beside the preview and linked
into each copy, and installed again only when the dependencies change."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from services import native_build, phone_preview as pp


world_full: list = [None]


@pytest.fixture
def world(tmp_path, monkeypatch):
    out = tmp_path / "app-root"
    real = out / "native"
    real.mkdir(parents=True)
    (real / "package.json").write_text(json.dumps({"dependencies": {"expo": "~51.0.0"}}), encoding="utf-8")
    ran: list[tuple[str, ...]] = []
    linked: list[tuple[Path, Path]] = []

    full: list[tuple[tuple, str]] = []

    async def fake_run(cmd, cwd, env, what):
        full.append((tuple(cmd), str(cwd)))
        ran.append(tuple(cmd[:3]))
        if cmd[0] == "npm":
            for name in pp.WEB_PACKAGES:
                (Path(cwd) / "node_modules" / name).mkdir(parents=True, exist_ok=True)
        return ""

    def fake_link(target, link):
        linked.append((Path(target), Path(link)))
        return True

    monkeypatch.setattr(pp, "_run", fake_run)
    monkeypatch.setattr(pp, "_write_status", lambda *a, **k: {})
    monkeypatch.setattr(pp, "native_dir", lambda output_dir: real)
    monkeypatch.setattr(native_build, "_link_packages", fake_link)

    def staged():
        d = tmp_path / f"staged-{len(ran)}-{len(linked)}"
        d.mkdir()
        return d

    world = (out, real, staged, ran, linked)
    world_full[0] = full
    return world


def build(world):
    out, real, staged, *_ = world
    asyncio.run(pp._ensure_packages(str(out), real, staged(), {}))


def test_the_first_redraw_installs_and_the_second_does_not(world):
    out, real, staged, ran, linked = world
    build(world)
    assert [c[0] for c in ran] == ["npm", "npx"]
    build(world)
    assert [c[0] for c in ran] == ["npm", "npx"]          # nothing more was run
    assert len(linked) == 2 and linked[0][0] == linked[1][0]   # both copies share the one kept folder


def test_a_changed_dependency_installs_again(world):
    out, real, staged, ran, linked = world
    build(world)
    (real / "package.json").write_text(json.dumps({"dependencies": {"expo": "~51.0.0", "left-pad": "1.0.0"}}), encoding="utf-8")
    build(world)
    assert [c[0] for c in ran] == ["npm", "npx", "npm", "npx"]


def test_a_project_with_its_own_packages_is_used_as_it_is(world):
    out, real, staged, ran, linked = world
    for name in pp.WEB_PACKAGES:
        (real / "node_modules" / name).mkdir(parents=True)
    build(world)
    assert ran == [] and linked == []


def test_a_project_missing_only_the_web_libraries_gets_them_once_into_its_own_packages(world):
    out, real, staged, ran, linked = world
    (real / "node_modules" / "expo").mkdir(parents=True)
    (real / "node_modules" / "expo" / "bundledNativeModules.json").write_text(
        json.dumps({"react-native-web": "~0.19.10", "react-dom": "18.2.0", "@expo/metro-runtime": "~3.2.3"}), encoding="utf-8")
    (real / "node_modules" / "@expo" / "metro-runtime").mkdir(parents=True)        # this one is there already
    build(world)
    command, where = world_full[0][-1]
    # npm, into the REAL project (not the throwaway copy, which is why they were added every time), and not saved:
    assert command[:3] == ("npm", "install", "--no-save") and where == str(real)
    assert "react-native-web@~0.19.10" in command and "react-dom@18.2.0" in command
    assert not any("metro-runtime" in part for part in command)
    assert (real / "package.json").read_text(encoding="utf-8") == json.dumps({"dependencies": {"expo": "~51.0.0"}})


def test_a_link_that_cannot_be_made_is_a_reason_not_a_crash(world, monkeypatch):
    out, real, staged, ran, linked = world
    monkeypatch.setattr(native_build, "_link_packages", lambda target, link: False)
    with pytest.raises(pp.PhonePreviewError):
        build(world)


# ---- putting the new picture in place --------------------------------------------------------------------------

def _folders(tmp_path):
    final, new = tmp_path / "dist", tmp_path / "building"
    final.mkdir()
    (final / "index.html").write_text("old", encoding="utf-8")
    new.mkdir()
    (new / "index.html").write_text("new", encoding="utf-8")
    return new, final


def test_the_new_picture_takes_the_old_ones_place(tmp_path):
    new, final = _folders(tmp_path)
    pp._swap(new, final)
    assert (final / "index.html").read_text(encoding="utf-8") == "new"
    assert not new.exists() and not list(tmp_path.glob("dist.old*")), "nothing of the old picture is left"


def test_the_first_picture_needs_no_old_one(tmp_path):
    new = tmp_path / "building"
    new.mkdir()
    (new / "index.html").write_text("new", encoding="utf-8")
    pp._swap(new, tmp_path / "dist")
    assert (tmp_path / "dist" / "index.html").read_text(encoding="utf-8") == "new"


def test_a_folder_that_is_busy_for_a_moment_is_tried_again(tmp_path, monkeypatch):
    """Windows says "Access is denied" to moving a folder with an open file, until the file is closed."""
    new, final = _folders(tmp_path)
    real, refused = os.replace, []

    def busy(src, dst):
        if Path(src) == final and len(refused) < 2:
            refused.append(1)
            raise PermissionError(5, "Access is denied")
        return real(src, dst)

    monkeypatch.setattr(pp.os, "replace", busy)
    monkeypatch.setattr(pp.time, "sleep", lambda s: None)
    pp._swap(new, final)
    assert len(refused) == 2 and (final / "index.html").read_text(encoding="utf-8") == "new"


def test_a_folder_that_stays_busy_keeps_the_old_picture_and_says_so(tmp_path, monkeypatch):
    new, final = _folders(tmp_path)
    real = os.replace

    def locked(src, dst):
        if Path(src) == new:
            raise PermissionError(5, "Access is denied")
        return real(src, dst)

    monkeypatch.setattr(pp.os, "replace", locked)
    monkeypatch.setattr(pp.time, "sleep", lambda s: None)
    with pytest.raises(pp.PhonePreviewError) as e:
        pp._swap(new, final)
    assert "could not be put in place" in str(e.value)
    assert (final / "index.html").read_text(encoding="utf-8") == "old", "the preview is never left without a picture"


# ---- the copy is made in the same place every time ---------------------------------------------------------------

def _real_project(tmp_path):
    real = tmp_path / "native"
    (real / "app").mkdir(parents=True)
    (real / "app" / "index.tsx").write_text("export default 1;\n", encoding="utf-8")
    (real / "package.json").write_text("{}", encoding="utf-8")
    (real / "node_modules" / "expo").mkdir(parents=True)
    (real / "node_modules" / "expo" / "kept.txt").write_text("the project's own package", encoding="utf-8")
    return real


def test_the_copy_is_in_the_same_place_every_time_and_is_clean(tmp_path):
    real, target = _real_project(tmp_path), tmp_path / "preview" / "stage"
    first = pp._stage_here(real, target)
    (first / "left-over.txt").write_text("from the last redraw", encoding="utf-8")
    (real / "app" / "new.tsx").write_text("export default 2;\n", encoding="utf-8")
    second = pp._stage_here(real, target)
    assert first == second == target, "the bundler's memory of a file includes where the project is, so it must not move"
    assert not (second / "left-over.txt").exists(), "and it is a clean copy each time"
    assert (second / "app" / "new.tsx").is_file() and (second / "app" / "index.tsx").is_file()


def test_the_projects_own_packages_are_never_deleted_through_the_link(tmp_path):
    """A junction (Windows) or a symlink is taken away as a link. A delete that followed it would empty the real packages."""
    real, target = _real_project(tmp_path), tmp_path / "preview" / "stage"
    pp._stage_here(real, target)
    assert (target / "node_modules").exists(), "the copy can read the project's packages"
    pp._stage_here(real, target)
    pp._stage_here(real, target)
    assert (real / "node_modules" / "expo" / "kept.txt").read_text(encoding="utf-8") == "the project's own package"


def test_the_project_itself_is_not_changed_by_a_copy(tmp_path):
    real, target = _real_project(tmp_path), tmp_path / "preview" / "stage"
    pp._stage_here(real, target)
    (target / "app" / "index.tsx").write_text("changed in the copy", encoding="utf-8")
    assert (real / "app" / "index.tsx").read_text(encoding="utf-8") == "export default 1;\n"


# ---- read-only files (the fonts the picture carries) --------------------------------------------------------------

def _folder_with_read_only_files(root: Path) -> Path:
    import stat
    root.mkdir(parents=True)
    for name in ("one.ttf", "two.ttf"):
        f = root / name
        f.write_text("font", encoding="utf-8")
        os.chmod(f, stat.S_IREAD)
    (root / "index.html").write_text("page", encoding="utf-8")
    return root


def test_a_folder_with_read_only_files_is_removed_whole(tmp_path):
    folder = _folder_with_read_only_files(tmp_path / "dist")
    pp._rmtree(folder)
    assert not folder.exists(), "a plain delete left the read-only fonts, and so the folder"


def test_removing_what_is_not_there_is_nothing(tmp_path):
    pp._rmtree(tmp_path / "never-made")


def test_a_picture_with_read_only_files_is_replaced_and_leaves_nothing_behind(tmp_path):
    """The Cart Buddy failure: every swap after the first was refused because a read-only leftover was in the way."""
    final = _folder_with_read_only_files(tmp_path / "dist")
    for n in range(3):
        new = _folder_with_read_only_files(tmp_path / "building")
        (new / "index.html").write_text(f"page {n}", encoding="utf-8")
        pp._swap(new, final)
        assert (final / "index.html").read_text(encoding="utf-8") == f"page {n}"
        assert not list(tmp_path.glob("dist.old*")) and not (tmp_path / "building").exists()


def test_a_leftover_from_an_earlier_swap_is_not_in_the_way(tmp_path):
    final = _folder_with_read_only_files(tmp_path / "dist")
    _folder_with_read_only_files(tmp_path / "dist.old")                  # what the failing version left behind
    new = _folder_with_read_only_files(tmp_path / "building")
    pp._swap(new, final)
    assert not list(tmp_path.glob("dist.old*")) and (final / "index.html").read_text(encoding="utf-8") == "page"


def test_a_folder_deeper_than_windows_allows_an_ordinary_path_is_still_removed(tmp_path):
    """The picture keeps each font under the project's whole path: 280 characters, with Windows' limit at 260."""
    if os.name != "nt":
        pytest.skip("the 260-character limit is Windows'")
    import stat
    root = tmp_path / "dist"
    deep = Path(pp._extended(root))
    for part in ("a" * 60, "b" * 60, "c" * 60, "d" * 60, "e" * 60):
        deep = deep / part
    os.makedirs(str(deep))
    font = deep / "Icons.ttf"
    font.write_text("font", encoding="utf-8")
    os.chmod(str(font), stat.S_IREAD)
    assert len(str(deep / "Icons.ttf")) > 300
    pp._rmtree(root)
    assert not root.exists()


def test_the_extended_form_is_only_for_windows(tmp_path):
    prefix = "\\\\?\\"
    text = pp._extended(tmp_path)
    assert text.startswith(prefix) if os.name == "nt" else not text.startswith(prefix)
    assert pp._extended(Path(text)) == text, "and it is not added twice"
