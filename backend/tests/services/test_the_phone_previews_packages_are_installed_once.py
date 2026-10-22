"""The phone preview installs the project's packages once, not on every redraw.

An app whose phone project has no `node_modules` installed its packages into the throwaway copy it builds in: about three
minutes of `npm install`, thrown away, on every redraw. They are now installed into a folder kept beside the preview and linked
into each copy, and installed again only when the dependencies change."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from services import native_build, phone_preview as pp


@pytest.fixture
def world(tmp_path, monkeypatch):
    out = tmp_path / "app-root"
    real = out / "native"
    real.mkdir(parents=True)
    (real / "package.json").write_text(json.dumps({"dependencies": {"expo": "~51.0.0"}}), encoding="utf-8")
    ran: list[tuple[str, ...]] = []
    linked: list[tuple[Path, Path]] = []

    async def fake_run(cmd, cwd, env, what):
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

    return out, real, staged, ran, linked


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


def test_a_project_missing_only_the_web_libraries_gets_them_added(world):
    out, real, staged, ran, linked = world
    (real / "node_modules" / "expo").mkdir(parents=True)
    build(world)
    assert [c[:2] for c in ran] == [("npx", "expo")]


def test_a_link_that_cannot_be_made_is_a_reason_not_a_crash(world, monkeypatch):
    out, real, staged, ran, linked = world
    monkeypatch.setattr(native_build, "_link_packages", lambda target, link: False)
    with pytest.raises(pp.PhonePreviewError):
        build(world)
