"""Connect a Figma file to the application, from a sentence.

`services.figma.cli` can already drive a live extraction, but it is a developer
harness — its own docstring says so. This is the same extraction reached the way
a user actually asks for it: "use this Figma design <url>".

WHAT SMITH ASKS FOR, AND WHAT IT NEVER ASKS FOR
-----------------------------------------------
The URL, yes. The token, never.

§42 lists where the raw credential must not come to rest and `chat history` is
first on that list. Smith's conversation is persisted, so a token typed into a
turn is a token written to disk in precisely the place the PRD forbids — and
this repository has already been burned by it once: `FIGMA_TOKEN` is annotated
in `.env` as leaked-in-chat.

`services.figma.credentials` had the answer before this module existed. A
`FigmaCredential` holds a *reference* — the name of the environment variable —
and the gateway resolves the secret at the moment of the call and discards it.
A name is not a secret, so Smith can ask for the name in conversation, store it
in the Blueprint, and print it back, all without ever holding the token.

So the exchange is:

    user   use the Figma design at https://figma.com/design/abc/Product?node-id=1-2
    smith  Which environment variable holds your Figma token? I need the NAME
           (for example FIGMA_TOKEN) — never paste the token itself.
    user   FIGMA_TOKEN
    smith  <extracts, connects, reports what the design does and does not say>

WHAT THE EXTRACTION IS FOR
--------------------------
Not the application. §48-§51 are firm that a design is *evidence*: a screen
proves a capability is reachable, and says nothing about who may use it, what
governs it, or what happens when it is refused. `figma_intelligence` turns the
frames into requirements a person can argue with, and `figma_design_system`
lets published variables outrank an invented palette. Both are ordinary DAG
nodes; this only puts the source in front of them.
"""
from __future__ import annotations

import asyncio
from typing import Any

#: Fields this verb needs. `token_env` is the NAME of an environment variable,
#: never the token — see the module docstring.
FIELDS = ("figma_url", "token_env")


class FigmaConnectError(RuntimeError):
    """Carries no secret. `FigmaGatewayError` already redacts its detail."""


def _run(coro: Any) -> Any:
    """Run an async extraction from Smith's synchronous turn.

    `asyncio.run` refuses to nest, and a Smith turn may itself be running
    inside a request loop. A dedicated thread with its own loop works from
    either, rather than being correct only in tests.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def summarise(ref: Any, record: dict) -> str:
    """§50's opener: what was found, then what the design cannot answer.

    The gaps are not decoration. Each is a question the design leaves open, and
    §48 wants those asked rather than inferred — a frame showing a table does
    not say who may read it.
    """
    counts = ref.summary()
    lines = [
        f"Connected {record.get('id')} — {ref.target.describe()}.",
        "",
        f"  {counts['screens']} screens ({counts['frames']} frames)",
        f"  {counts['components']} components, "
        f"{counts['interactions']} prototype interactions",
        f"  {counts['colorTokens']} colour tokens, "
        f"{counts['typographyTokens']} typography tokens",
    ]
    named = [s.name for s in ref.screens if getattr(s, "looks_like_screen", False)]
    if named:
        lines += ["", "Screens: " + ", ".join(named[:12])
                  + (f" and {len(named) - 12} more" if len(named) > 12 else "")]
    if ref.gaps:
        lines += ["", "What the design does not answer:"]
        lines += [f"  - {g}" for g in ref.gaps[:6]]
    if str(record.get("treatAs")) == "specification":
        lines += [
            "",
            "Held as the SPECIFICATION: the application gets one page per frame "
            "above and no others. Nothing will be added around them — no "
            "sign-in, no lists behind the numbers, no forms to create what they "
            "show — unless you drew it. Say “build” when you want the run.",
        ]
    else:
        lines += [
            "",
            "Held as EVIDENCE: these become requirements you can review, not "
            "decisions — a screen proves a capability is reachable, not who may "
            "use it. The page set is derived from the data model with these "
            "informing it, so expect more screens than frames. Say “build” when "
            "you want the run.",
        ]
    return "\n".join(lines)


def connect(output_dir: Any, *, figma_url: str, token_env: str,
            treat_as: str = "evidence",
            max_screens: int = 40, with_images: bool = True) -> dict[str, Any]:
    """Extract the design and attach it to the Blueprint.

    Returns ``{"record": <designSources entry>, "summary": <text>}``.

    Raises :class:`FigmaConnectError` with a message safe to show a user —
    every underlying error type either redacts itself or names only the
    reference.
    """
    from services.figma.credentials import (
        EnvSecretResolver, FigmaCredential, FigmaCredentialError,
    )
    from services.figma.gateway import (
        DEFAULT_ENDPOINT, FigmaGateway, FigmaGatewayError,
    )
    from services.figma.reference import extract
    from services.figma.store import connect as attach
    from services.figma.url import parse

    # VALIDATED BEFORE ANYTHING EXPENSIVE OR FALLIBLE. Loading the Blueprint
    # first meant a mistyped link was reported as whatever went wrong next —
    # "could not read that Figma file: FileNotFoundError" for a URL that was
    # simply not a Figma URL.
    target = parse(figma_url)
    if target is None:
        raise FigmaConnectError(
            f"That does not look like a Figma URL: {figma_url!r}. I need the "
            f"link from Figma's Share dialog, like "
            f"https://figma.com/design/<key>/<name>?node-id=1-2"
        )

    ref_name = (token_env or "").strip()
    if not ref_name:
        raise FigmaConnectError(
            "I need the NAME of the environment variable holding your Figma "
            "token — for example FIGMA_TOKEN. Never paste the token itself: it "
            "would be written to the conversation log (§42)."
        )

    from services.blueprint.service import BlueprintService

    svc = BlueprintService.load(output_dir=str(output_dir))

    # THE STORE FIRST, THE ENVIRONMENT AS FALLBACK. `credentials.py` calls
    # `EnvSecretResolver` the stand-in for "before the platform secrets service
    # exists" — it exists, and `__figma__` now declares its keys, so the token
    # is per-organisation and encrypted at rest instead of shared in a .env
    # every project on the machine can read.
    #
    # The endpoint travels with it: the desktop app's Dev Mode server only runs
    # while Figma is open on one person's machine, so it is a real setting and
    # a bad default.
    from services.figma.integrations import (
        MappingResolver, config_for, endpoint_from,
    )

    values = config_for(output_dir)
    resolver = (MappingResolver(values) if values.get(ref_name)
                else EnvSecretResolver())

    gateway = FigmaGateway(
        credential=FigmaCredential(ref=ref_name),
        resolver=resolver,
        endpoint=endpoint_from(values),
    )
    try:
        ref = _run(extract(gateway, target, max_screens=max_screens,
                           with_images=with_images))
    except FigmaCredentialError as exc:
        # Names the reference, never the value — that is the whole point of the
        # credential being a reference.
        raise FigmaConnectError(
            f"I could not read a Figma token from {ref_name}: {exc}. Export it "
            f"in the environment the backend runs in, then ask me again."
        ) from exc
    except FigmaGatewayError as exc:
        # `.detail` is already redacted by the gateway.
        raise FigmaConnectError(f"Figma {exc.kind}: {exc.detail}") from exc

    record = attach(svc, ref, treat_as=treat_as)
    return {"record": record, "summary": summarise(ref, record)}
