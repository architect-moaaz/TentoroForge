"""What the Agent Builder's model calls cost, and the limits that keep that cost bounded.

"Find problems" and the Test console call the model with the PLATFORM's key. Until now nothing stopped them or counted
them: the model name and ``maxTokens`` were read straight from the drawing, and one click on "Find problems" could make
hundreds of calls (tests x repeats x turns, a simulated lookup for each tool call, a judge) with no balance check, no limit
check and no row in the usage ledger. This is the one place that closes that, in four parts:

* ``gate``      the same door every other piece of paid work goes through (``services.credits.gate``): a balance too low,
                or a limit reached, is an HTTP 402 in the administrator's words, BEFORE the first call.
* ``Meter``     a count of calls for one run, with a hard cap. A call over the cap is not made: it raises
                ``CallLimitReached`` with a plain sentence, and the caller stops and says so.
* ``clamp_*``   the model name must be one the platform has chosen to allow, and ``maxTokens`` is cut to a server-side
                maximum, because both come from a drawing anyone with edit rights can change.
* recording     every call's real token usage is written to the build-usage ledger under the application, the person and
                the organisation that spent it (``services.build_usage.record_usage``), so the Usage pages and the spend
                limits see it.

``Meter.client()`` / ``Meter.wrap()`` give a client that does all of that on every ``messages.create``, so no caller has to
remember to.
"""
from __future__ import annotations

import os
import re
import time
from typing import Any, Callable


def _env_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, "") or default)
    except ValueError:
        return default
    return value if value > 0 else default


#: The most model calls ONE "Find problems" run may make. A full blast (20 tests, 3 runs each) is about 250 calls; this
#: leaves room for long conversations and 40 tests, and stops a run that goes further than anyone meant it to.
MAX_BLAST_CALLS = _env_int("FORGE_AGENT_TEST_MAX_CALLS", 500)
#: The most calls one of the smaller actions may make (inventing tests, studying a tool, proposing fixes): each is one to
#: four calls, with a retry.
MAX_HELPER_CALLS = _env_int("FORGE_AGENT_HELPER_MAX_CALLS", 20)
#: The most calls one message in the Test console may make (it makes one).
MAX_CONSOLE_CALLS = 3
#: The longest answer any one call may ask for, whatever the drawing says.
MAX_OUTPUT_TOKENS = _env_int("FORGE_AGENT_TEST_MAX_TOKENS", 4096)
#: What one call is expected to cost, for the check before a run starts (the real cost is recorded afterwards).
ESTIMATE_PER_CALL_USD = 0.02

#: The models a drawing may ask for when it is tested. Anything else is replaced by the platform's own model. More can be
#: allowed with FORGE_AGENT_TEST_MODELS (comma separated).
_BASE_MODELS = ("claude-sonnet-4-6", "claude-haiku-4-5")
_DATED = re.compile(r"^(?P<base>.+)-\d{8}$")
_FALLBACK_MODEL = "claude-sonnet-4-6"


def platform_model() -> str:
    """The model the platform itself uses for these tests when the drawing's is not allowed."""
    return os.getenv("ANTHROPIC_MODEL") or _FALLBACK_MODEL


def allowed_models() -> set[str]:
    extra = {m.strip() for m in os.getenv("FORGE_AGENT_TEST_MODELS", "").split(",") if m.strip()}
    platform = {m for m in (os.getenv("ANTHROPIC_MODEL"), os.getenv("FORGE_BLAST_MODEL")) if m}
    return {*_BASE_MODELS, *extra, *platform, _FALLBACK_MODEL}


def clamp_model(name: Any) -> tuple[str, str]:
    """``(model to use, a note for the person)``: the drawing's model when it is allowed (a dated id of an allowed model
    counts), else the platform's, with a note saying so. The note is empty when nothing was changed."""
    wanted = str(name or "").strip()
    allowed = allowed_models()
    if not wanted:
        return platform_model(), ""
    dated = _DATED.match(wanted)
    if wanted in allowed or (dated and dated.group("base") in allowed):
        return wanted, ""
    use = platform_model()
    return use, f"This agent asks for the model \"{wanted[:60]}\", which the test tools do not run; {use} was used instead."


def clamp_max_tokens(value: Any) -> int:
    """The answer length to ask for: the drawing's, but never above the server's maximum, and never nonsense."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return MAX_OUTPUT_TOKENS
    return max(1, min(n, MAX_OUTPUT_TOKENS))


class CallLimitReached(RuntimeError):
    """The run asked for more model calls than it is allowed. A ``RuntimeError`` so the routers say it as a plain 400 where
    they already do for a model that cannot be reached."""


class Meter:
    """The calls of ONE run: how many, how many tokens, and who pays. ``max_calls`` is a hard stop. Without a ``project`` the
    calls are counted and capped but not written to the ledger (there is nobody to write them under)."""

    def __init__(self, *, agent: str, project: str = "", user: str = "", org: str = "", max_calls: int | None = None):
        self.agent, self.project, self.user, self.org = agent, project, user, org
        self.max_calls = int(max_calls) if max_calls else MAX_BLAST_CALLS
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.stopped = ""

    @property
    def exhausted(self) -> bool:
        return self.calls >= self.max_calls

    def limit_message(self) -> str:
        return (f"Stopped: this run reached its limit of {self.max_calls} model calls. What finished is shown; "
                f"run fewer tests, or fewer repeats, to cover the rest.")

    def take(self) -> None:
        """Count one call about to be made, or refuse it. Counted before the call so that calls in flight side by side
        cannot all slip under the cap."""
        if self.calls >= self.max_calls:
            self.stopped = self.limit_message()
            raise CallLimitReached(self.stopped)
        self.calls += 1

    def record(self, model: str, response: Any, started: float) -> None:
        """Write one answered call's real usage to the ledger. Never raises: counting must not fail the work."""
        usage = getattr(response, "usage", None)
        got = {k: int(getattr(usage, k, 0) or 0) for k in
               ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")}
        self.input_tokens += got["input_tokens"]
        self.output_tokens += got["output_tokens"]
        if not self.project:
            return
        try:
            from services.build_usage import record_usage
            # phase "change": work on an application that already exists, which is how the spend pages read it.
            record_usage(project=self.project, agent=self.agent, model=model, usage=got, kind="agent_test",
                         phase="change", user=self.user, org=self.org, duration_ms=int((time.perf_counter() - started) * 1000))
        except Exception:  # noqa: BLE001
            pass

    def wrap(self, inner: Any) -> "MeteredClient":
        """``inner`` (anything with ``messages.create``) with this meter on every call; one already metered is left as it is."""
        return inner if isinstance(inner, MeteredClient) else MeteredClient(self, inner=inner)

    def client(self, make: Callable[[], Any]) -> "MeteredClient":
        """A metered client whose real client is made by ``make`` on its FIRST call, so a missing key is reported where the
        first call is made, as it always was, and not before the caller's own checks."""
        return MeteredClient(self, make=make)


class _Messages:
    def __init__(self, owner: "MeteredClient"):
        self._owner = owner

    async def create(self, **req: Any) -> Any:
        owner = self._owner
        owner.meter.take()
        req = {**req, "model": clamp_model(req.get("model"))[0], "max_tokens": clamp_max_tokens(req.get("max_tokens"))}
        started = time.perf_counter()
        response = await owner.inner().messages.create(**req)
        owner.meter.record(req["model"], response, started)
        return response


class MeteredClient:
    """Stands in for ``anthropic.AsyncAnthropic`` where only ``messages.create`` is used: counts and caps the calls, keeps the
    model and the answer length inside what the server allows, and records the usage."""

    def __init__(self, meter: Meter, *, inner: Any = None, make: Callable[[], Any] | None = None):
        self.meter = meter
        self._inner, self._make = inner, make
        self.messages = _Messages(self)

    def inner(self) -> Any:
        if self._inner is None:
            self._inner = self._make() if self._make else None
        return self._inner


def meter_for(project: Any, user: Any, agent: str, max_calls: int | None = None) -> Meter:
    """A meter for work a person starts on an application: spend is written under that application, person and organisation."""
    return Meter(agent=agent, project=str(getattr(project, "short_id", "") or ""), user=str(getattr(user, "email", "") or ""),
                 org=str(getattr(project, "org_id", "") or ""), max_calls=max_calls)


async def gate(db: Any, project: Any, user: Any, *, calls: int) -> None:
    """Refuse (HTTP 402, in the administrator's words) work the organisation cannot pay for: the balance must cover about
    ``calls`` model calls and no limit over the platform, the organisation, the person or the application may be reached.
    The same door the build and every Smith turn go through."""
    from services import credits

    await credits.gate(db, org_id=getattr(project, "org_id", ""), user_email=str(getattr(user, "email", "") or ""),
                       project_short_id=str(getattr(project, "short_id", "") or ""),
                       estimate=round(max(1, calls) * ESTIMATE_PER_CALL_USD, 4))
