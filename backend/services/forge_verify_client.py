"""Python client for the forge-verify Playwright runner (SV-4).

Talks HTTP to the `forge-verify` container (spec §5.7). One-shot per run
— the client polls until done OR (when the caller cares about live
progress) subscribes to the SSE stream and yields events.
"""
from __future__ import annotations

import asyncio
import json
import os
from dataclasses import asdict, is_dataclass
from typing import Any, AsyncIterator, Callable, Awaitable

import httpx


class ForgeVerifyError(RuntimeError):
    """Raised when the runner service is unreachable or the run fails."""


def _default_base_url() -> str:
    return os.environ.get("FORGE_VERIFY_URL", "http://forge-verify:6600")


def _to_jsonable(value: Any) -> Any:
    """Turn dataclasses / tuples into JSON-safe primitives.

    interaction_extractor emits frozen dataclasses with tuple fields;
    the runner expects arrays. This handles the whole tree.
    """
    if is_dataclass(value):
        return _to_jsonable(asdict(value))
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(v) for v in value]
    return value


class ForgeVerifyClient:
    """Async client. `async with ForgeVerifyClient() as c: ...` recommended."""

    def __init__(self, base_url: str | None = None, timeout: float = 30.0) -> None:
        self.base_url = (base_url or _default_base_url()).rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout)

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "ForgeVerifyClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    async def healthz(self) -> bool:
        try:
            r = await self._client.get(f"{self.base_url}/healthz")
            return r.status_code == 200 and r.json().get("ok") is True
        except httpx.HTTPError:
            return False

    async def run(
        self,
        project_id: str,
        target: str,          # "preview" | "deploy"
        base_url: str,
        interactions: list,   # Interaction[] — frozen dataclasses accepted
        *,
        auth: dict | None = None,
        interaction_timeout_ms: int = 15_000,
    ) -> str:
        """Kick off a run, return the runner's run_id."""
        payload = {
            "project_id": project_id,
            "target": target,
            "base_url": base_url,
            "interactions": _to_jsonable(interactions),
            "interaction_timeout_ms": interaction_timeout_ms,
        }
        if auth is not None:
            payload["auth"] = auth
        try:
            r = await self._client.post(f"{self.base_url}/run", json=payload)
        except httpx.HTTPError as e:
            raise ForgeVerifyError(f"runner unreachable: {e}") from e
        if r.status_code != 200:
            raise ForgeVerifyError(
                f"runner rejected run: status={r.status_code} body={r.text!r}",
            )
        return r.json()["run_id"]

    async def get(self, run_id: str) -> dict:
        r = await self._client.get(f"{self.base_url}/run/{run_id}")
        if r.status_code == 404:
            raise ForgeVerifyError(f"run {run_id} not found")
        r.raise_for_status()
        return r.json()

    async def poll_until_done(
        self, run_id: str, *, interval: float = 1.5,
        timeout: float | None = None,
        on_progress: Callable[[dict], Any] | None = None,
        should_cancel: Callable[[], Awaitable[bool]] | None = None,
    ) -> dict:
        """Poll `GET /run/:id` until status is `done` or `failed`.

        No wall-clock ceiling by default — the previous 600s/1800s hard
        caps kept firing before Playwright finished (see JV-2X debug):
        the sidecar completed with real data but we killed the poll and
        marked the row `failed` with counts=NULL, so the UI showed
        "0/93 passed" while the runner actually had 45/93 · 48 faults.

        Instead the loop bails on a **heartbeat gap** — consecutive
        failed pings to the sidecar. That catches a truly-dead sidecar
        (crash / kill) without punishing legitimately-long runs.

        Overrides:
          - explicit ``timeout=<seconds>`` restores the old wall-clock
            behaviour for callers that need it (e.g. CI).
          - ``FORGE_VERIFY_POLL_TIMEOUT=<seconds>`` env var — same.
          - ``FORGE_VERIFY_POLL_HEARTBEAT_GAP=<seconds>`` — how long the
            sidecar can be unreachable before we give up (default 60s).
        """
        if timeout is None:
            env_v = os.environ.get("FORGE_VERIFY_POLL_TIMEOUT")
            timeout = float(env_v) if env_v else None  # None → wait forever
        heartbeat_gap = float(
            os.environ.get("FORGE_VERIFY_POLL_HEARTBEAT_GAP", "60"),
        )
        loop = asyncio.get_event_loop()
        started = loop.time()
        last_ok = loop.time()
        while True:
            # JV-27/#4 — cancellation gate. Caller-provided coroutine that
            # returns True when the run has been cancelled (typically:
            # DB row status == 'cancelled'). Bailing early stops the
            # background poll from clobbering the row after cancel.
            if should_cancel is not None:
                try:
                    if await should_cancel():
                        raise ForgeVerifyError(f"run {run_id}: cancelled")
                except ForgeVerifyError:
                    raise
                except Exception:  # noqa: BLE001
                    pass  # cancellation-check must not fail the poll
            try:
                resp = await self.get(run_id)
                last_ok = loop.time()
            except (httpx.HTTPError, ForgeVerifyError) as e:
                if loop.time() - last_ok > heartbeat_gap:
                    raise ForgeVerifyError(
                        f"run {run_id}: sidecar unreachable for "
                        f"{heartbeat_gap:.0f}s ({e!r})",
                    ) from e
                await asyncio.sleep(interval)
                continue
            # JV-27/#1+#3 — fire the progress callback on every successful
            # poll so callers can publish live counter + streaming-fault
            # events. Never blocks the poll — swallow any callback error.
            if on_progress is not None:
                try:
                    res = on_progress(resp)
                    if asyncio.iscoroutine(res):
                        await res
                except Exception:  # noqa: BLE001
                    pass
            status = resp.get("status")
            if status in ("done", "failed"):
                return resp
            if timeout is not None and loop.time() - started > timeout:
                raise ForgeVerifyError(f"run {run_id} did not finish within {timeout}s")
            await asyncio.sleep(interval)

    async def stream(self, run_id: str) -> AsyncIterator[dict]:
        """Yield SSE events for a run. Terminates on verify.done/failed."""
        url = f"{self.base_url}/run/{run_id}/stream"
        # SSE = long-lived GET with text/event-stream. httpx handles chunked
        # reads via stream=True.
        async with self._client.stream("GET", url, timeout=None) as r:
            r.raise_for_status()
            event = ""
            data = ""
            async for line in r.aiter_lines():
                if not line:
                    if event:
                        try:
                            yield {"type": event, "data": json.loads(data or "{}")}
                        except json.JSONDecodeError:
                            yield {"type": event, "data": {"raw": data}}
                        if event in ("verify.done", "verify.failed"):
                            return
                    event = ""
                    data = ""
                elif line.startswith("event: "):
                    event = line[7:].strip()
                elif line.startswith("data: "):
                    data = line[6:]
