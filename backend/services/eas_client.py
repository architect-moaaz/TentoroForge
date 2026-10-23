"""MOBILE-C — EAS Build client (subprocess wrapper).

Shells out to ``npx eas build`` in the generated app's ``mobile/``
folder. The CLI is the primary programmatic interface Expo supports —
their internal REST/GraphQL API isn't publicly documented, so
wrapping the CLI (like every CI setup does) is the least fragile
path.

Two public functions:

    ``create_build(...)``  — enqueues a build; returns build id + logs URL
    ``poll_build(...)``    — reads current status of an existing build

Both are async and return typed :class:`BuildState`. Failures raise
:class:`EasClientError` with the CLI's stderr for diagnosis. The CLI
must be installed on the backend host — the Dockerfile adds
``npm i -g eas-cli`` at build time; local dev needs
``npm i -g eas-cli`` once.

Test-injectable seam: pass ``run=<coro>`` to override the subprocess
runner. Tests use this to return canned CLI output without a network
call. Live callers use the default runner.
"""
from __future__ import annotations

import asyncio
import re
import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional


logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Types                                                                        #
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class BuildState:
    """Snapshot of an EAS build's state, normalized across `create` +
    `poll`. Fields track the on-disk model 1:1 so the caller can copy
    them straight into a ``MobileBuild`` row.

    ``status`` mirrors EAS's own values: pending / in_progress /
    finished / errored / canceled. We normalize to our shorter set at
    the DB layer.
    """

    build_id: str
    status: str
    artifact_url: Optional[str] = None
    logs_url: Optional[str] = None
    error_message: Optional[str] = None


class EasClientError(RuntimeError):
    """Raised on non-zero CLI exit or unparseable output."""


# --------------------------------------------------------------------------- #
# Subprocess runner (injectable)                                               #
# --------------------------------------------------------------------------- #

# (argv, cwd, env) -> (returncode, stdout, stderr)
RunFn = Callable[
    [list[str], str, dict[str, str]],
    Awaitable[tuple[int, str, str]],
]


async def _default_run(
    argv: list[str], cwd: str, env: dict[str, str],
) -> tuple[int, str, str]:
    """Default runner — invokes the CLI as a real subprocess."""
    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=cwd,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_b, stderr_b = await proc.communicate()
    return proc.returncode or 0, stdout_b.decode("utf-8", errors="replace"), \
           stderr_b.decode("utf-8", errors="replace")


# --------------------------------------------------------------------------- #
# Env building                                                                 #
# --------------------------------------------------------------------------- #

#: What Windows needs in a child's environment for Node to work at all. Without SYSTEMROOT, Node cannot look up a host name
#: (`getaddrinfo EAI_FAIL`: npm could not even download eas-cli), and without USERPROFILE / APPDATA / TEMP npm has no cache.
#: Nothing on Linux or macOS needs these, so the list is read only there where it is Windows.
_WINDOWS_ENV = (
    "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP",
    "HOMEDRIVE", "HOMEPATH", "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "PROCESSOR_ARCHITECTURE",
    "NUMBER_OF_PROCESSORS", "USERNAME",
)


def _inherited_windows_env() -> dict[str, str]:
    if os.name != "nt":
        return {}
    return {key: os.environ[key] for key in _WINDOWS_ENV if key in os.environ}


def _tail(text: str, size: int = 700) -> str:
    """The END of a command's output: the warnings come first and the reason last (a 500-character head was only
    "punycode is deprecated ... using EAS without version control")."""
    return (text or "").strip()[-size:]


#: What the CLI prints on every run, which says nothing about why it failed.
_NOISE = re.compile(r"punycode|DEP0040|--trace-deprecation|without version control|Failed to get Git root|"
                    r"Falling back to using current|EAS_PROJECT_ROOT")


def _reason(stdout: str, stderr: str, size: int = 900) -> str:
    """Why a CLI command failed: both streams together, the noise it always prints left out, the end of what is left.

    Only the error stream was shown when it had any text at all, and the line that named the cause was in the other one: a
    build failed with "project:init command failed" and the sentence above it ("Failed to resolve plugin for module
    expo-router ... Do you have node modules installed?") never reached the person (2026-10-22)."""
    lines = ((stdout or "") + chr(10) + (stderr or "")).splitlines()
    kept = [line.rstrip() for line in lines if line.strip() and not _NOISE.search(line)]
    return chr(10).join(kept).strip()[-size:]


def _build_env(
    expo_token: str,
    deployed_url: str,
    extra: Optional[dict[str, str]] = None,
) -> dict[str, str]:
    """Compose the subprocess env: inherit the parent's PATH so we can
    find npx / node, inject the Expo token so ``eas build`` is
    authenticated, and expose the deployed URL as
    ``EXPO_PUBLIC_APP_URL`` so App.tsx points at the right host.

    Extra keys (Apple/Google credentials for a store submission) are
    merged last.
    """
    env = {
        # Inherit path + basic locale so npx resolves and node can print
        # unicode logs.
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME") or os.environ.get("USERPROFILE") or "/tmp",
        "LANG": os.environ.get("LANG", "en_US.UTF-8"),
        **_inherited_windows_env(),
        # eas-cli authentication
        "EXPO_TOKEN": expo_token,
        # WebView shell URL
        "EXPO_PUBLIC_APP_URL": deployed_url or "",
    }
    if extra:
        env.update(extra)
    return env


# --------------------------------------------------------------------------- #
# create_build                                                                 #
# --------------------------------------------------------------------------- #

async def create_build(
    mobile_dir: str,
    *,
    profile: str,
    platform: str,
    expo_token: str,
    deployed_url: str,
    apple_env: Optional[dict[str, str]] = None,
    google_env: Optional[dict[str, str]] = None,
    extra_env: Optional[dict[str, str]] = None,
    run: RunFn = _default_run,
) -> BuildState:
    """Enqueue an EAS build for the app in ``mobile_dir``.

    Runs::

        npx eas-cli build --profile <profile> --platform <platform>
            --non-interactive --json --no-wait

    ``--no-wait`` returns immediately with the build id in stdout JSON;
    the caller polls status separately.

    Raises :class:`EasClientError` on non-zero exit or if the CLI's
    output doesn't parse. The caller is expected to persist ``pending``
    → ``in_progress`` on success and ``failed`` on error.
    """
    if profile not in ("preview", "preview-simulator", "production", "development"):
        raise EasClientError(f"unknown build profile: {profile!r}")
    if platform not in ("android", "ios"):
        raise EasClientError(f"platform must be android or ios, got {platform!r}")
    if not expo_token:
        raise EasClientError("expo_token is required")

    argv = [
        "npx", "eas-cli", "build",
        "--profile", profile,
        "--platform", platform,
        "--non-interactive",
        "--json",
        "--no-wait",
    ]
    env = _build_env(expo_token, deployed_url, {**(apple_env or {}), **(google_env or {}), **(extra_env or {})})

    rc, stdout, stderr = await run(argv, mobile_dir, env)
    if rc != 0:
        raise EasClientError(
            f"eas build exited {rc}: {_reason(stdout, stderr)}"
        )

    # CLI --json --no-wait returns a JSON array (one entry per platform requested).
    payload = _parse_cli_json(stdout, context="create_build")
    entries = payload if isinstance(payload, list) else [payload]
    if not entries:
        raise EasClientError("eas build returned no build entries")
    return _to_build_state(entries[0])


# --------------------------------------------------------------------------- #
# link_project                                                                 #
# --------------------------------------------------------------------------- #

#: A folder under `output/` is not a git repository of its own, and may sit INSIDE ours: EAS would take our repository as
#: the project and upload (or ignore) the wrong thing. `EAS_NO_VCS=1` makes the folder itself the project.
NO_VCS = {"EAS_NO_VCS": "1"}


async def link_project(
    native_dir: str,
    *,
    expo_token: str,
    project_id: str = "",
    run: RunFn = _default_run,
) -> None:
    """Link the folder to an EAS project (made under the token's account when there is none): ``eas init``, which
    writes the project id into ``app.json``. Raises :class:`EasClientError` with the CLI's words when it cannot."""
    if not expo_token:
        raise EasClientError("expo_token is required")
    argv = ["npx", "eas-cli", "init", "--non-interactive", "--force"]
    if project_id:
        argv += ["--id", project_id]          # link to the project that already exists, never make a second one
    rc, stdout, stderr = await run(argv, native_dir, _build_env(expo_token, "", NO_VCS))
    if rc != 0:
        raise EasClientError(f"eas init exited {rc}: {_reason(stdout, stderr)}")


# --------------------------------------------------------------------------- #
# submit_build                                                                 #
# --------------------------------------------------------------------------- #

async def submit_build(
    project_dir: str,
    *,
    build_id: str,
    platform: str,
    expo_token: str,
    extra_env: Optional[dict[str, str]] = None,
    run: RunFn = _default_run,
) -> str:
    """Send a finished build to its store: ``eas submit --id <build> --profile production``. It WAITS for the upload (a
    minute or two), so a clean return means the store has the build; the store's own processing and review come after.

    ``project_dir`` must hold an eas.json whose ``submit.production`` names the store key files
    (``native_build.write_submit_keys``). Returns the CLI's last words (where to find the build). Raises
    :class:`EasClientError` with the end of its output when it fails."""
    if platform not in ("android", "ios"):
        raise EasClientError(f"platform must be android or ios, got {platform!r}")
    if not expo_token or not build_id:
        raise EasClientError("expo_token and build_id are required")
    argv = ["npx", "eas-cli", "submit", "--platform", platform, "--id", build_id, "--profile", "production", "--non-interactive"]
    rc, stdout, stderr = await run(argv, project_dir, _build_env(expo_token, "", extra_env))
    if rc != 0:
        raise EasClientError(f"eas submit exited {rc}: {_reason(stdout, stderr)}")
    return _tail(stdout, 300)


# --------------------------------------------------------------------------- #
# poll_build                                                                   #
# --------------------------------------------------------------------------- #

async def poll_build(
    mobile_dir: str,
    build_id: str,
    *,
    expo_token: str,
    run: RunFn = _default_run,
) -> BuildState:
    """Read current status of a queued build. Runs::

        npx eas-cli build:view <build_id> --json

    Returns a fresh :class:`BuildState`. Callers write the mirrored
    fields onto the ``MobileBuild`` row and, when status is terminal
    (finished / errored / canceled), stamp ``completed_at``.
    """
    if not build_id:
        raise EasClientError("build_id is required")

    argv = ["npx", "eas-cli", "build:view", build_id, "--json"]
    env = _build_env(expo_token, deployed_url="")

    rc, stdout, stderr = await run(argv, mobile_dir, env)
    if rc != 0:
        raise EasClientError(
            f"eas build:view exited {rc}: {stderr[:500] or stdout[:500]}"
        )

    payload = _parse_cli_json(stdout, context="poll_build")
    return _to_build_state(payload)


# --------------------------------------------------------------------------- #
# Parsing helpers                                                              #
# --------------------------------------------------------------------------- #

def _parse_cli_json(stdout: str, *, context: str) -> Any:
    """Robust CLI JSON extractor. The CLI usually prints ONLY JSON when
    ``--json`` is set, but occasionally emits a warning line first
    (npm deprecation notices, etc.). Grab the last balanced JSON blob
    from stdout and parse that — falls back to a raise if nothing looks
    like JSON."""
    text = stdout.strip()
    if not text:
        raise EasClientError(f"{context}: eas returned empty stdout")
    # Fast path: whole stdout is JSON.
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Fallback: find the first {...} or [...] block.
    for opener, closer in (("[", "]"), ("{", "}")):
        start = text.find(opener)
        if start < 0:
            continue
        end = text.rfind(closer)
        if end > start:
            candidate = text[start:end + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue
    raise EasClientError(
        f"{context}: eas output didn't contain JSON — got {text[:200]!r}"
    )


def _to_build_state(entry: dict[str, Any]) -> BuildState:
    """Normalize an EAS build record into :class:`BuildState`.

    The CLI's shape uses ``id`` + ``status`` + ``artifacts.buildUrl``
    for the downloadable artifact and ``buildLogsUrl`` for the human
    logs page. Field names have shifted over CLI versions; we defensive-
    pick from a couple of aliases so a minor CLI bump doesn't silently
    break parsing.
    """
    if not isinstance(entry, dict):
        raise EasClientError(f"expected object, got {type(entry).__name__}")

    build_id = entry.get("id") or entry.get("buildId") or ""
    status = (entry.get("status") or "unknown").lower()

    # Artifact URL — CLI 5+ uses artifacts.buildUrl; older builds put it
    # at top-level artifactUrl.
    artifact_url = None
    artifacts = entry.get("artifacts")
    if isinstance(artifacts, dict):
        artifact_url = artifacts.get("buildUrl") or artifacts.get("applicationArchiveUrl")
    artifact_url = artifact_url or entry.get("artifactUrl")

    logs_url = entry.get("buildLogsUrl") or entry.get("logsUrl")

    err = None
    if isinstance(entry.get("error"), dict):
        err = entry["error"].get("message") or entry["error"].get("errorCode")
    elif isinstance(entry.get("errorMessage"), str):
        err = entry["errorMessage"]

    return BuildState(
        build_id=build_id,
        status=status,
        artifact_url=artifact_url,
        logs_url=logs_url,
        error_message=err,
    )


# --------------------------------------------------------------------------- #
# DB status mapping                                                            #
# --------------------------------------------------------------------------- #

# EAS statuses that mean "still going". Anything else is terminal.
_ACTIVE_EAS_STATUSES = {"pending", "new", "in_queue", "in_progress"}
_SUCCESS_EAS_STATUSES = {"finished", "succeeded", "completed"}
_FAILURE_EAS_STATUSES = {"errored", "failed"}
_CANCELED_EAS_STATUSES = {"canceled", "cancelled"}


def normalize_status(eas_status: str) -> str:
    """Map an EAS status string into our DB enum (pending / in_progress /
    completed / failed / canceled). Any unknown value bucket as
    ``in_progress`` so a stuck poll doesn't false-terminate the row."""
    s = (eas_status or "").lower().replace("-", "_")
    if s in _ACTIVE_EAS_STATUSES:
        # "in-queue" means waiting for a build worker — still pending
        # from a user POV. Only "in-progress" is actively running.
        return "in_progress" if s == "in_progress" else "pending"
    if s in _SUCCESS_EAS_STATUSES:
        return "completed"
    if s in _FAILURE_EAS_STATUSES:
        return "failed"
    if s in _CANCELED_EAS_STATUSES:
        return "canceled"
    return "in_progress"


def is_terminal(db_status: str) -> bool:
    """True when the build won't change further — the poller loop stops."""
    return db_status in {"completed", "failed", "canceled"}
