"""Shared plumbing for the live checks: they drive a RUNNING Forge (backend on
:6500, its Postgres, and Docker for app previews) as real people.

Accounts. `admin@tentoro.ai` and `visitor@example.com` are ordinary sign-ups on
the local platform; their passwords are read from backend/.env lines
`# TEMPLATE_GALLERY_ADMIN: <email> / <password>` (and `..._VISITOR`). The
builder is the local `dev.tester@example.com`, signed in with a token minted
from the platform's own secret, so no password of theirs is needed.

Pace. The platform allows two requests a second per address with a burst of
twenty; a script is far faster than a person, so every request here waits its
turn — what is tested is the feature, not the rate limiter.
"""
from __future__ import annotations

import asyncio
import io
import os
import re
import sys
import time
import uuid
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BACKEND / ".env", override=True)

import httpx  # noqa: E402

API = os.environ.get("FORGE_API", "http://localhost:6500")
ENV = (BACKEND / ".env").read_text()
DSN = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
PACE = {"request": [lambda _r: time.sleep(0.55)]}

passed = 0


def check(cond: object, label: str) -> None:
    global passed
    print(("PASS " if cond else "FAIL ") + label, flush=True)
    if not cond:
        raise SystemExit(1)
    passed += 1


def client(token: str, *, paced: bool = True, timeout: float = 300) -> httpx.Client:
    return httpx.Client(base_url=API, headers={"Authorization": f"Bearer {token}"}, timeout=timeout,
                        event_hooks=PACE if paced else None)


def login(key: str, email: str) -> str:
    pw = re.search(rf"{key}: {re.escape(email)} / (\S+)", ENV)
    if not pw:
        raise SystemExit(f"No password for {email} in backend/.env ({key})")
    r = httpx.post(f"{API}/api/auth/login", json={"email": email, "password": pw.group(1)}, timeout=60)
    r.raise_for_status()
    return r.json()["access_token"]


def admin() -> httpx.Client:
    return client(login("TEMPLATE_GALLERY_ADMIN", "admin@tentoro.ai"))


def visitor() -> httpx.Client:
    return client(login("TEMPLATE_GALLERY_VISITOR", "visitor@example.com"))


def builder_token(email: str = "dev.tester@example.com") -> tuple[str, str]:
    """A session for a local account without its password: (token, org id)."""
    import asyncpg

    from auth import create_access_token

    async def go():
        c = await asyncpg.connect(DSN)
        row = await c.fetchrow("select u.id, m.org_id from platform_users u join org_members m "
                               "on m.user_id = u.id where u.email = $1 limit 1", email)
        await c.close()
        return create_access_token(uuid.UUID(str(row["id"])), uuid.UUID(str(row["org_id"]))), str(row["org_id"])
    return asyncio.run(go())


def png(w: int = 160, h: int = 100, color=(20, 120, 200)) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


def app_session(port: int, short: str) -> tuple[httpx.Client, str]:
    """Signed in to a generated app's preview as its seeded admin."""
    app = f"http://localhost:{port}/api/projects/{short}/preview/serve"
    seed = (BACKEND.parent / "output" / short / "app" / "src" / "db" / "seed.ts").read_text()
    email = re.search(r'SEED_ADMIN_EMAIL \|\| "([^"]+)"', seed).group(1)
    pw = re.search(r'SEED_ADMIN_PASSWORD \|\| "([^"]+)"', seed).group(1)
    a = httpx.Client(timeout=300)
    csrf = a.get(f"{app}/api/auth/csrf").json()["csrfToken"]
    a.post(f"{app}/api/auth/callback/credentials",
           data={"csrfToken": csrf, "email": email, "password": pw, "callbackUrl": app})
    return a, app


def done() -> None:
    print(f"\nALL {passed} LIVE CHECKS PASSED", flush=True)
