"""Windows runs the platform's `["npm", ...]` and `["npx", ...]` argument lists.

The platform starts its tools (npm install, tsc, drizzle-kit, the dev server) as plain argument lists. Windows cannot
start `npm` that way: the file is `npm.cmd`, so the very first build step died with `FileNotFoundError: [WinError 2]`
and nothing after it ran. Here the few tool names are resolved through PATH when a process is started. Nothing happens
off Windows, and a name that is not found is left as it was."""
from __future__ import annotations

import os
import shutil
import subprocess

TOOLS = ("npm", "npx", "node", "tsc", "tsx", "esbuild")

_installed = False


def resolve_tools_on_windows() -> bool:
    """Make `subprocess` find `npm.cmd` and the other tools by their short names. True when it was installed now."""
    global _installed
    if os.name != "nt" or _installed:
        return False
    original = subprocess.Popen.__init__

    def init(self, args, *a, **kw):
        if isinstance(args, (list, tuple)) and args and args[0] in TOOLS:
            found = shutil.which(args[0])
            if found:
                args = [found, *args[1:]]
        original(self, args, *a, **kw)

    subprocess.Popen.__init__ = init
    _installed = True
    return True
