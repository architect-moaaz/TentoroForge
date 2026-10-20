"""An application's own switches, kept with the project: today, its MCP server.

The owner decides whether assistants may connect to the application
(`services.blueprint.app_mcp`). That is not part of what the application IS —
the Blueprint does not change when it is turned on — so it is kept beside the
project, in `.forge/app-settings.json`, where the platform's routes and
Smith both read and write it.

The application reads it as `FORGE_APP_MCP` (`on` / `off`). The preview's
`.env.local` is written at once, and `next dev` reloads its environment when
that file changes; a published app is given the value with its next publish,
because a deployment's environment is fixed when it is made.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PATH = Path(".forge") / "app-settings.json"
MCP_ENV = "FORGE_APP_MCP"


def read(output_dir: str | Path | None) -> dict[str, Any]:
    if not output_dir:
        return {}
    try:
        data = json.loads((Path(output_dir) / PATH).read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def mcp_enabled(output_dir: str | Path | None) -> bool:
    return bool((read(output_dir).get("mcpServer") or {}).get("enabled"))


def env_for(output_dir: str | Path | None) -> dict[str, str]:
    """The variables the app reads its switches from — always given, so a
    publish that turns one off overwrites the value an earlier one set."""
    return {MCP_ENV: "on" if mcp_enabled(output_dir) else "off"}


def set_mcp(output_dir: str | Path, enabled: bool, *, by: str = "") -> dict[str, Any]:
    """Turn the app's MCP server on or off; writes the preview's environment too."""
    import time

    data = read(output_dir)
    data["mcpServer"] = {"enabled": bool(enabled), "changedAt": time.time(), "changedBy": by}
    path = Path(output_dir) / PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), "utf-8")
    write_preview_env(output_dir)
    return data["mcpServer"]


def write_preview_env(output_dir: str | Path) -> bool:
    """Put the switches into the preview's `.env.local`, in place: a line that
    is there is replaced, otherwise one is added. True when the file changed."""
    from services.env_writer import app_env_dir

    root = app_env_dir(output_dir)
    if not (root / "package.json").is_file():
        return False
    env_path = root / ".env.local"
    try:
        text = env_path.read_text("utf-8") if env_path.is_file() else ""
    except OSError:
        return False
    new = text
    for key, value in env_for(output_dir).items():
        line = f"{key}={value}"
        pattern = re.compile(rf"^\s*{re.escape(key)}\s*=.*$", re.M)
        if pattern.search(new):
            new = pattern.sub(line, new, count=1)
        else:
            new = (new.rstrip("\n") + "\n" if new.strip() else "") + line + "\n"
    if new == text:
        return False
    tmp = env_path.with_suffix(".local.tmp")
    tmp.write_text(new, "utf-8")
    tmp.replace(env_path)
    logger.info("[app-settings] %s: %s", env_path, ", ".join(f"{k}={v}" for k, v in env_for(output_dir).items()))
    return True


__all__ = ["MCP_ENV", "env_for", "mcp_enabled", "read", "set_mcp", "write_preview_env"]
