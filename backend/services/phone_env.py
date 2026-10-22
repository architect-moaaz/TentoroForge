"""The environment the phone project's own processes run in: Metro, Expo, npm and its package scripts.

PR #28 review (2026-10-22): these processes ran in the platform's environment (`{**os.environ}`), so `DATABASE_URL`, `SECRET_KEY` and
the model keys reached code the project controls: a package's install script, an `app.config.js` (its `extra` is served from the
live preview's manifest without a sign-in) and Expo's `+api` routes. `preview.app_env` already keeps those out of an app's own
processes (2026-10-09); this is the same, and also drops anything whose NAME says it is a secret, because the platform's
environment holds more than the list `app_env` knows (cloud keys, tokens, a payment provider's keys).
"""
from __future__ import annotations

import re
from pathlib import Path

#: A name that says it holds a secret.
_SECRET_NAME = re.compile(r"(?:^|_)(?:KEY|KEYS|SECRET|SECRETS|TOKEN|TOKENS|PASSWORD|PASSWD|PWD|CREDENTIAL|CREDENTIALS|DSN)(?:_|$)"
                          r"|DATABASE_URL|CONNECTION_STRING|PRIVATE", re.I)
#: Names that match the pattern above and that a toolchain needs: the key of the shell's own agent is not one of them, and neither is
#: anything npm uses to reach a registry (a project's packages come from the public one).
_KEEP = frozenset({"PATHEXT", "PSMODULEPATH"})


def phone_env(output_dir: str | Path, **extra: str) -> dict[str, str]:
    """`preview.app_env` for the project, without anything named like a secret, plus `extra`."""
    from preview import app_env

    env = {k: v for k, v in app_env(str(output_dir)).items() if k.upper() in _KEEP or not _SECRET_NAME.search(k)}
    env.update(extra)
    return env
