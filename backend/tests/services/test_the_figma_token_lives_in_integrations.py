"""The Figma credential belongs in the store, not in a shared .env.

`credentials.py` calls `EnvSecretResolver` the stand-in written "for local
development and live verification **before the platform secrets service
exists**". It exists — `platform_integrations` is per-organisation, encrypted
at rest with a per-provider HKDF subkey, and already holds the Anthropic and
Resend keys.

A token in a shared `.env` is a token every project and every developer on the
machine holds, with no owner and no rotation story. That is how the one in this
repository came to be annotated as leaked-in-chat.

Two properties. Figma is a provider the settings page can render, and the
resolver prefers the store while the environment keeps working — nothing has to
be migrated before this is useful, and a developer mid-extraction is not broken
by the change.
"""
import pytest

from services.figma.integrations import (
    ENDPOINT_KEY, MappingResolver, PROVIDER, TOKEN_KEY, endpoint_from,
)
from services.node_config_specs import all_providers, keys_for_provider


# ------------------------------------------------------------ the catalogue

def test_figma_is_a_provider_the_settings_page_can_render():
    assert PROVIDER in all_providers()


def test_the_token_is_write_only():
    """`kind="password"` is never echoed back by the settings API, so the
    value can go in and cannot be read out through the UI."""
    token = next(k for k in keys_for_provider(PROVIDER) if k.key == TOKEN_KEY)
    assert token.kind == "password"
    assert token.required is True


def test_the_endpoint_is_optional_and_defaults_to_the_remote():
    """The desktop app's Dev Mode server only runs while Figma is open on one
    person's machine — a legitimate setting and a poor default for a backend."""
    ep = next(k for k in keys_for_provider(PROVIDER) if k.key == ENDPOINT_KEY)
    assert ep.required is False
    assert ep.default == "https://mcp.figma.com/mcp"


# ------------------------------------------------------------- the resolver

def test_a_stored_value_resolves():
    assert MappingResolver({TOKEN_KEY: "tok"}).resolve(TOKEN_KEY) == "tok"


@pytest.mark.parametrize("values", [{}, {TOKEN_KEY: ""}, {TOKEN_KEY: "   "}])
def test_a_missing_value_raises_the_same_error_the_env_resolver_raises(values):
    """Callers must not be able to tell which backend answered — that is what
    makes the seam a seam rather than a fallback chain."""
    from services.figma.credentials import FigmaCredentialError

    with pytest.raises(FigmaCredentialError):
        MappingResolver(values).resolve(TOKEN_KEY)


def test_the_resolver_holds_only_what_it_was_given():
    """The raw secret lives for one extraction inside one object, rather than
    being reachable from anything holding a database session."""
    r = MappingResolver({TOKEN_KEY: "tok"})
    with pytest.raises(Exception):
        r.resolve("ANTHROPIC_API_KEY")


# ------------------------------------------------------------- the endpoint

def test_a_configured_endpoint_wins():
    assert endpoint_from({ENDPOINT_KEY: "http://127.0.0.1:3845/mcp"}) \
        == "http://127.0.0.1:3845/mcp"


@pytest.mark.parametrize("values", [{}, {ENDPOINT_KEY: ""}, {ENDPOINT_KEY: "  "}])
def test_no_endpoint_falls_back_rather_than_returning_empty(values):
    """An empty endpoint would be a connection error with no explanation."""
    assert endpoint_from(values).startswith("http")


# ------------------------------------------------------ degrading gracefully

def test_config_for_never_raises_on_an_unknown_directory(tmp_path, monkeypatch):
    """A project with no row, a database that is down, and an organisation that
    configured nothing all mean "fall back" — never "fail the turn"."""
    from services.figma import integrations

    async def down(*_a, **_k):
        raise RuntimeError("database is down")

    monkeypatch.setattr(integrations, "_org_for_output_dir", down)
    monkeypatch.delenv(TOKEN_KEY, raising=False)
    assert integrations.config_for(tmp_path) == {}


def test_the_environment_still_works_when_nothing_is_stored(tmp_path, monkeypatch):
    """Nothing has to be migrated before this is useful."""
    from services.figma import integrations

    async def nothing(*_a, **_k):
        return None

    monkeypatch.setattr(integrations, "_org_for_output_dir", nothing)
    monkeypatch.setenv(TOKEN_KEY, "from-env")
    assert integrations.config_for(tmp_path).get(TOKEN_KEY) == "from-env"
