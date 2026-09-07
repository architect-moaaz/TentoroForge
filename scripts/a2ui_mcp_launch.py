"""Launch the agent2ui MCP server with Forge's own .env loaded.

`.mcp.json` can only expand ${VAR} from the environment it is already given,
so without this the key would have to be pasted a second time into that file.
Forge's backend/.env is the single place a secret lives; this reads it and
execs the real server, so there is exactly one copy of the key on disk.

Parsing is deliberately minimal — KEY=VALUE, '#' comments, optional quotes —
because dotenv is a backend dependency and this runs in the agent2ui venv.
"""
from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent.parent / "backend" / ".env"
SERVER = os.environ.get("A2UI_SERVER") or ""


def load_env(path: Path) -> None:
    if not path.is_file():
        print(f"[a2ui-launch] no {path}; relying on inherited env", file=sys.stderr)
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        # Never let the file override something explicitly exported.
        if key and val and key not in os.environ:
            os.environ[key] = val


load_env(ENV_FILE)

if not SERVER:
    sys.exit("[a2ui-launch] set A2UI_SERVER to the path of server.py")
if not os.environ.get("ANTHROPIC_API_KEY"):
    print("[a2ui-launch] warning: ANTHROPIC_API_KEY still empty", file=sys.stderr)

# The server resolves sibling imports (generator, providers) from its own dir.
sys.path.insert(0, os.path.dirname(os.path.abspath(SERVER)))
sys.argv = [SERVER]
runpy.run_path(SERVER, run_name="__main__")
