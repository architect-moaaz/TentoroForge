"""Passing a browser's requests to a project's live phone server (see `services/phone_live.py`), and nothing else.

The dev server is a development tool with endpoints that open files in an editor, run a debugger and read the project; it was never meant
to face a browser. So this passes on only what the page needs to draw and update itself: the page, its bundle, its fonts and pictures, and the
two live-update sockets. Everything else is refused here, before it reaches the server, whoever asks.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import AsyncIterator, Optional

import httpx

from services import phone_preview as pp

logger = logging.getLogger(__name__)

#: What the page asks the dev server for: the page itself, bundles, source maps, fonts and pictures, a few static files.
_ALLOWED = re.compile(
    r"""^/(
        $                                            # the page
      | .+\.bundle$                                   # the app (its path climbs out of the project when the packages are linked)
      | [^/]*\.map$
      | assets(?:/.*)?$                                # fonts and pictures: `/assets/?unstable_path=…` names the file in its query
      | _expo/.+
      | [^/]+\.(?:png|jpe?g|gif|svg|ico|ttf|otf|woff2?|json|js|css)$
    )""", re.X)
#: The two sockets the page opens (patched to carry the path prefix).
SOCKETS = ("/hot", "/message")

_HOP = {"connection", "keep-alive", "transfer-encoding", "te", "trailer", "upgrade", "proxy-authorization", "proxy-authenticate",
        "content-length", "content-encoding", "host"}


def allowed(path: str) -> bool:
    """Is this path one a browser may ask the dev server for?"""
    return bool(_ALLOWED.match(path if path.startswith("/") else "/" + path))


def own_file(path: str) -> Optional[tuple[str, str]]:
    """The two scripts the editor adds to the page are the platform's, not the dev server's: `(file, media type)` or None."""
    if path == "/__bridge.js":
        return str(pp.STATIC / "bridge.js"), "application/javascript"
    if path == "/__fit.js":
        return str(pp.ASSETS / "fit.js"), "application/javascript"
    return None


def _no_dot_segments(rest: str) -> str:
    """A path that climbs (`../../native/node_modules/…`) with its slashes written as `%2F`, which Metro reads back as slashes.

    The packages are linked from the real phone project, so the app's entry file is outside the project and Metro names it by climbing out.
    On Windows it writes the climb with backslashes, which a browser leaves alone. On Linux it writes plain `../`, and a browser removes
    those before asking, so the request would never arrive under the prefix at all (found by reasoning about Linux, 2026-10-22). Written as
    `..%2F` it is one ordinary name to the browser and the same path to Metro."""
    return re.sub(r"(?:^|(?<=/))((?:\.\./)+)", lambda m: m.group(1).replace("/", "%2F"), rest)


def rewrite_html(html: str, prefix: str) -> str:
    """The dev server's page, made to work under the path it is served from.

    Its links start at the top of the host (`/index.bundle…`), which here is the platform's own site, so each is moved under `prefix`; the
    page learns the prefix (for its sockets) before anything else runs; and the editor's bridge and fit scripts are added, as the built
    picture gets them."""
    html = re.sub(r'(\s(?:src|href)=")/(?!/)([^"]*)',
                  lambda m: m.group(1) + prefix + "/" + _no_dot_segments(m.group(2).split("?", 1)[0]) + ("?" + m.group(2).split("?", 1)[1] if "?" in m.group(2) else ""),
                  html)
    # Expo's router strips its base path only in a production build; in development it expects to be at the top of the host and, under
    # `prefix`, finds no screen ("This screen does not exist", Cart Buddy 2026-10-22). So before the app starts the page moves its own
    # address to the top of the host, keeping the screen it was opened at (`prefix/bought` becomes `/bought`). Nothing is reloaded.
    head = ("<script>window.__FORGE_LIVE__=" + json.dumps(prefix) + ";(function(){var p=window.__FORGE_LIVE__,l=window.location;"
            "if(l.pathname.indexOf(p)===0){history.replaceState(history.state,'',(l.pathname.slice(p.length)||'/')+l.search+l.hash);}})();</script>")
    html = html.replace("<head>", "<head>" + head, 1) if "<head>" in html else head + html
    tags = f'<script src="{prefix}/__bridge.js"></script><script src="{prefix}/__fit.js"></script>'
    return html.replace("</body>", tags + "</body>", 1) if "</body>" in html else html + tags


#: How the dev server's bundles name a font or a picture: from the top of the host, written into the code as plain text.
_ASSET_ADDRESS = '"/assets/?unstable_path='


def rewrite_bundle(text: str, prefix: str) -> str:
    """The app's code (and a live update of it), with its fonts' and pictures' addresses moved under `prefix`.

    Expo's start command fixes where assets are served from (`/assets/?unstable_path=…`, from the top of the host) and writes it into every
    asset it bundles, so the icon font was asked for at the platform's own address and got a 404: no icons in the live picture (Cart Buddy,
    2026-10-22). The address is plain text in the code, so it is moved under the path the page is served from."""
    return text.replace(_ASSET_ADDRESS, '"' + prefix + _ASSET_ADDRESS[1:])


def upstream_path(raw_path: bytes, prefix: str) -> str:
    """What the dev server is asked for: the raw path (kept exactly as sent, including encoded characters) without the prefix."""
    text = raw_path.decode("latin-1")
    rest = text[len(prefix):] if text.startswith(prefix) else text
    return rest if rest.startswith("/") else "/" + rest


async def fetch(port: int, path: str, query: str, method: str, accept: Optional[str]) -> tuple[httpx.Response, httpx.AsyncClient]:
    """Open the dev server's answer; the caller streams it and closes the client."""
    client = httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=5.0))
    url = f"http://127.0.0.1:{port}{path}" + (f"?{query}" if query else "")
    headers = {"accept-encoding": "identity", **({"accept": accept} if accept else {})}
    request = client.build_request(method, url, headers=headers)
    return await client.send(request, stream=True), client


def response_headers(upstream: httpx.Response) -> dict[str, str]:
    return {k: v for k, v in upstream.headers.items() if k.lower() not in _HOP}


async def stream(upstream: httpx.Response, client: httpx.AsyncClient) -> AsyncIterator[bytes]:
    try:
        async for chunk in upstream.aiter_raw():
            yield chunk
    finally:
        await upstream.aclose()
        await client.aclose()


def unprefixed(text: str, prefix: str) -> str:
    """What the page says over a socket, as the dev server should hear it.

    The live-update socket tells the dev server which bundle the page is running by its full address, which carries the path the page is
    served from. The dev server reads the address's path as a file to find, did not find `/api/projects/…/phone/live/…`, and stopped: the
    whole server, not just that socket (Cart Buddy, 2026-10-22). The same address without the prefix is the one it built the bundle for.
    Only the written path is changed: the prefix inside the address's query (the app's base path, URL-encoded) is the bundle's own."""
    return text.replace(prefix + "/", "/")


async def pump(websocket, port: int, path: str, prefix: str = "") -> None:
    """Carry one live-update socket both ways until either side closes."""
    from websockets.asyncio.client import connect
    async with connect(f"ws://127.0.0.1:{port}{path}", open_timeout=10, max_size=None, ping_interval=None) as upstream:
        async def up() -> None:
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    return
                if message.get("text") is not None:
                    await upstream.send(unprefixed(message["text"], prefix) if prefix else message["text"])
                elif message.get("bytes") is not None:
                    await upstream.send(message["bytes"])

        async def down() -> None:
            async for message in upstream:
                if isinstance(message, str):
                    await websocket.send_text(rewrite_bundle(message, prefix) if prefix else message)
                else:
                    await websocket.send_bytes(message)

        tasks = [asyncio.create_task(up()), asyncio.create_task(down())]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        for task in done:
            exc = task.exception()
            if exc is not None:
                logger.debug("[phone_live] socket ended: %s", exc)
