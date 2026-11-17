"""The preview proxy keeps no cookies.

An httpx client stores every Set-Cookie it is answered with and sends it with
every later request it builds. The proxy's one shared client did, so the first
person to sign in to a preview had their session sent with everyone else's
requests: a signed-out visitor read the app as them (`/api/billing/status`
answered `access: true` to a request with no cookie, 2026-11-11).
"""
from __future__ import annotations

import asyncio

import httpx

from routers import preview_proxy as pp


def test_the_proxys_client_keeps_no_cookie_it_is_answered_with():
    seen: list[str | None] = []

    def app(req: httpx.Request) -> httpx.Response:
        seen.append(req.headers.get("cookie"))
        return httpx.Response(200, headers={"set-cookie": "next-auth.session-token=someone; Path=/; HttpOnly"})

    async def run():
        client = httpx.AsyncClient(transport=httpx.MockTransport(app), cookies=pp._NO_COOKIES)
        await client.send(httpx.Request("GET", "http://localhost:3201/api/projects/x/preview/serve/login"))
        await client.send(httpx.Request("GET", "http://localhost:3201/api/projects/x/preview/serve/api/tasks"))
        await client.send(client.build_request("GET", "http://localhost:3201/api/projects/x/preview/serve/tasks"))
        return len(client.cookies.jar)

    assert asyncio.run(run()) == 0
    assert seen == [None, None, None], "a later visitor was sent an earlier one's session"


def test_the_shared_client_is_the_one_that_keeps_none():
    assert pp._client.cookies.jar is pp._NO_COOKIES
    assert pp._NO_COOKIES._policy.allowed_domains() == ()
