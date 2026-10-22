"""The first Cart Buddy phone build failed at `eas init` with "project:init command failed" and nothing else.

The real reason was in the line above it, which the platform threw away: "Failed to resolve plugin for module expo-router ...
Do you have node modules installed?". The phone project's packages had never been installed: the `install` node installs the web
app's, the type-check toolchain is its own folder, and Expo needs the project's own on this machine to read its plugins.
Now they are installed before Expo is asked, and a failed Expo command says the line that names the cause."""
from __future__ import annotations

import asyncio
import json
import types

import pytest

from routers import mobile_builds as mb
from services import eas_client, native_build

URL = "https://example.vercel.app"


def project(tmp_path, with_packages=False, with_package_json=True):
    root = tmp_path / "native"
    root.mkdir()
    if with_package_json:
        (root / "package.json").write_text(json.dumps({"dependencies": {"expo": "~51.0.0"}}), "utf-8")
    if with_packages:
        (root / "node_modules" / "expo").mkdir(parents=True)
    return root


def installer(root, *, rc=0, said="", leave_expo=True):
    ran = []

    async def run(argv, cwd, timeout):
        ran.append((tuple(argv), cwd))
        if rc == 0 and leave_expo:
            (root / "node_modules" / "expo").mkdir(parents=True, exist_ok=True)
        return rc, said

    return run, ran


def test_missing_packages_are_installed_in_the_phone_project(tmp_path):
    root = project(tmp_path)
    run, ran = installer(root)
    assert asyncio.run(native_build.ensure_packages(root, run=run)) is True
    assert ran == [(("npm", "install", "--no-audit", "--no-fund"), str(root))]


def test_packages_that_are_there_are_left_alone(tmp_path):
    root = project(tmp_path, with_packages=True)
    run, ran = installer(root)
    assert asyncio.run(native_build.ensure_packages(root, run=run)) is False
    assert ran == []


def test_a_failed_install_says_what_npm_said(tmp_path):
    root = project(tmp_path)
    run, ran = installer(root, rc=1, said="npm error code E404\nnpm error 404 Not Found - GET https://registry/nope")
    with pytest.raises(native_build.NativeBuildError) as e:
        asyncio.run(native_build.ensure_packages(root, run=run))
    assert "npm exited 1" in str(e.value) and "404 Not Found" in str(e.value)


def test_an_install_that_leaves_no_expo_is_a_reason(tmp_path):
    root = project(tmp_path)
    run, ran = installer(root, leave_expo=False)
    with pytest.raises(native_build.NativeBuildError) as e:
        asyncio.run(native_build.ensure_packages(root, run=run))
    assert "`expo` is not among them" in str(e.value)


def test_a_project_without_a_package_json_is_a_reason(tmp_path):
    root = project(tmp_path, with_package_json=False)
    with pytest.raises(native_build.NativeBuildError) as e:
        asyncio.run(native_build.ensure_packages(root))
    assert "no package.json" in str(e.value)


def test_a_failed_install_fails_the_build_with_the_reason_and_never_reaches_expo(tmp_path, monkeypatch):
    failed, linked = [], []

    async def broken(root, **kw):
        raise native_build.NativeBuildError("installing the phone project's packages failed (npm exited 1): E404")

    async def link(root, token):
        linked.append(root)
        return "p"

    async def mark(row, message):
        failed.append(message)

    monkeypatch.setattr(mb.native_build, "ensure_packages", broken)
    monkeypatch.setattr(mb.native_build, "ensure_eas_project", link)
    monkeypatch.setattr(mb, "_mark_failed", mark)
    creds = types.SimpleNamespace(expo_eas_token="tok", apple=None, google=None)
    asyncio.run(mb._run_build_and_poll("row", str(tmp_path), "preview", "android", creds, URL, "native"))
    assert failed == ["installing the phone project's packages failed (npm exited 1): E404"]
    assert linked == []


# ---- what a failed Expo command says ---------------------------------------------------------------------------

STDOUT = ("Failed to get Git root path with `git rev-parse --show-toplevel`. Error: exited with non-zero code: 128\n"
          "Falling back to using current working directory as project root.\n"
          'Failed to resolve plugin for module "expo-router" relative to "C:\\x". Do you have node modules installed?\n')
STDERR = ("(node:11796) [DEP0040] DeprecationWarning: The `punycode` module is deprecated.\n"
          "(Use `node --trace-deprecation ...` to show where the warning was created)\n"
          "Using EAS CLI without version control system is not recommended, use this mode only if you know what you are doing.\n"
          "    Error: project:init command failed.\n")


def test_the_cause_is_kept_when_the_error_stream_has_text_too():
    said = eas_client._reason(STDOUT, STDERR)
    assert "Failed to resolve plugin for module" in said and "Do you have node modules installed?" in said
    assert "project:init command failed" in said


def test_the_noise_the_cli_always_prints_is_left_out():
    said = eas_client._reason(STDOUT, STDERR)
    for noise in ("punycode", "trace-deprecation", "without version control", "Failed to get Git root", "Falling back"):
        assert noise not in said


def test_a_failed_link_carries_the_cause_in_its_error():
    async def run(argv, cwd, env):
        return 1, STDOUT, STDERR

    with pytest.raises(eas_client.EasClientError) as e:
        asyncio.run(eas_client.link_project("x", expo_token="t", run=run))
    assert "exited 1" in str(e.value) and "Do you have node modules installed?" in str(e.value)
