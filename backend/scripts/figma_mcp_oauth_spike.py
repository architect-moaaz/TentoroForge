"""Spike: does Figma's hosted MCP (mcp.figma.com/mcp) serve our extraction
tools over OAuth?

This drives the EXACT path production would use — `mcp`'s OAuthClientProvider
(PKCE, dynamic client registration if the server offers it, token exchange,
refresh) feeding `streamablehttp_client(url, auth=...)`. If it works here, the
production build is plumbing; if it doesn't, we learned that in an afternoon.

WHAT IT ANSWERS
  1. Auth — does OAuth against mcp.figma.com actually authenticate? (PATs don't.)
  2. get_design_context — does the HOSTED server return the structure/text a
     page is composed from, for a file by API, with no desktop app? (The Dev
     Mode server needs the file open; this is the open question.)
  3. Rate/latency — how many calls and how long for one file's three tools.

HOW TO RUN
  A Figma account is all that may be needed. From backend/:

      python scripts/figma_mcp_oauth_spike.py

  It prints an authorize URL. Open it in a browser, sign in to Figma and
  approve; the browser redirects to http://localhost:{PORT}/callback, which
  this script is listening on. You never paste a token — the script captures
  the code and exchanges it itself.

  If Figma's MCP requires a PRE-REGISTERED app (i.e. dynamic registration is
  refused), register one at figma.com/developers, set its redirect URI to
  http://localhost:{PORT}/callback, and export:

      export FIGMA_OAUTH_CLIENT_ID=...        # optional; DCR is tried first
      export FIGMA_OAUTH_CLIENT_SECRET=...

  Override the probed file with FIGMA_FILE_KEY / FIGMA_NODE_ID (defaults are the
  Case-Management file this session used).
"""
from __future__ import annotations

import asyncio
import os
import time
import webbrowser
from urllib.parse import parse_qs, urlparse

from mcp import ClientSession
from mcp.client.auth import OAuthClientProvider, TokenStorage
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken

SERVER_URL = os.environ.get("FIGMA_MCP_URL", "https://mcp.figma.com/mcp")
PORT = int(os.environ.get("FIGMA_OAUTH_CALLBACK_PORT", "3456"))
REDIRECT_URI = f"http://localhost:{PORT}/callback"
FILE_KEY = os.environ.get("FIGMA_FILE_KEY", "llRwGmNM8NX72r9r4gmnEq")
NODE_ID = os.environ.get("FIGMA_NODE_ID", "1:2")


class MemoryStorage(TokenStorage):
    """The spike keeps tokens in memory. Production implements this same
    protocol over the encrypted platform_integrations store."""

    def __init__(self) -> None:
        self._tokens: OAuthToken | None = None
        self._client: OAuthClientInformationFull | None = None

    async def get_tokens(self) -> OAuthToken | None:
        return self._tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self._tokens = tokens

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        return self._client

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self._client = client_info


async def _capture_code() -> tuple[str, str | None]:
    """Run a one-shot localhost server and return the (code, state) Figma
    redirects back with."""
    got: dict[str, str] = {}
    ready = asyncio.Event()

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        line = await reader.readline()
        try:
            target = line.decode().split(" ", 2)[1]
            q = parse_qs(urlparse(target).query)
            got["code"] = (q.get("code") or [""])[0]
            got["state"] = (q.get("state") or [""])[0]
        except Exception:  # noqa: BLE001
            pass
        body = b"<html><body>Figma connected. You can close this tab and return to the terminal.</body></html>"
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n"
                     b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body)
        await writer.drain()
        writer.close()
        ready.set()

    server = await asyncio.start_server(handle, "localhost", PORT)
    async with server:
        await asyncio.wait_for(ready.wait(), timeout=300)
    return got.get("code", ""), got.get("state") or None


async def _redirect(url: str) -> None:
    print("\n=== OPEN THIS URL IN YOUR BROWSER, SIGN IN TO FIGMA, AND APPROVE ===\n")
    print(url + "\n")
    try:
        webbrowser.open(url)
    except Exception:  # noqa: BLE001
        pass


def _client_metadata() -> OAuthClientMetadata:
    return OAuthClientMetadata(
        client_name="Tentoro Forge (spike)",
        redirect_uris=[REDIRECT_URI],
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        token_endpoint_auth_method="client_secret_post",
    )


async def main() -> None:
    print(f"server:   {SERVER_URL}")
    print(f"file:     {FILE_KEY} / {NODE_ID}")
    print(f"callback: {REDIRECT_URI}")

    storage = MemoryStorage()
    cid = os.environ.get("FIGMA_OAUTH_CLIENT_ID")
    if cid:
        # A pre-registered app: seed the client info so DCR is skipped.
        storage._client = OAuthClientInformationFull(
            client_id=cid,
            client_secret=os.environ.get("FIGMA_OAUTH_CLIENT_SECRET"),
            redirect_uris=[REDIRECT_URI],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            token_endpoint_auth_method="client_secret_post",
        )
        print("using pre-registered client id from the environment")
    else:
        print("no client id set — trying dynamic client registration first")

    auth = OAuthClientProvider(
        server_url=SERVER_URL,
        client_metadata=_client_metadata(),
        storage=storage,
        redirect_handler=_redirect,
        callback_handler=_capture_code,
    )

    t0 = time.time()
    async with streamablehttp_client(SERVER_URL, auth=auth) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print(f"\n[ok] authenticated + initialized in {time.time()-t0:.1f}s")

            tools = await session.list_tools()
            names = [t.name for t in tools.tools]
            print(f"[ok] server advertises {len(names)} tools:", ", ".join(names))

            for tool, args in (
                ("get_metadata", {"fileKey": FILE_KEY, "nodeId": NODE_ID}),
                ("get_design_context", {"fileKey": FILE_KEY, "nodeId": NODE_ID}),
                ("get_screenshot", {"fileKey": FILE_KEY, "nodeId": NODE_ID}),
            ):
                if tool not in names:
                    print(f"[MISS] {tool}: not advertised by the hosted server")
                    continue
                s = time.time()
                try:
                    res = await session.call_tool(tool, arguments=args)
                    size = sum(len(getattr(b, "text", "") or "") for b in res.content)
                    kinds = sorted({type(b).__name__ for b in res.content})
                    verdict = "HAS CONTENT" if size or "ImageContent" in kinds else "EMPTY"
                    print(f"[{tool}] {time.time()-s:.1f}s | {verdict} | {size} chars | blocks {kinds}")
                except Exception as exc:  # noqa: BLE001
                    print(f"[{tool}] FAILED after {time.time()-s:.1f}s: {type(exc).__name__}: {str(exc)[:200]}")

    print("\n=== VERDICT ===")
    print("If get_design_context shows HAS CONTENT, the hosted MCP serves the")
    print("extraction headlessly over OAuth and production is plumbing. If it is")
    print("EMPTY/MISS/FAILED, the hosted server does not give what a build needs.")


if __name__ == "__main__":
    asyncio.run(main())
