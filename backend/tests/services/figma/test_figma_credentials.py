"""§42 — the token must not come to rest anywhere this platform writes."""
import pytest

from services.figma.credentials import (
    EnvSecretResolver,
    FigmaCredential,
    FigmaCredentialError,
    looks_like_token,
    redact,
)

REAL_LOOKING = "figd_fixture_not_a_real_token"


def test_credential_holds_a_reference():
    cred = FigmaCredential(ref="FIGMA_PAT", label="Acme workspace")
    assert cred.ref == "FIGMA_PAT"


def test_raw_token_as_ref_is_rejected():
    """The failure this guards is a token stored in the Blueprint because the
    field accepted a string."""
    with pytest.raises(FigmaCredentialError, match="raw Figma token"):
        FigmaCredential(ref=REAL_LOOKING)


def test_empty_ref_is_rejected():
    with pytest.raises(FigmaCredentialError):
        FigmaCredential(ref="  ")


def test_repr_cannot_leak_a_value_it_never_holds():
    assert "figd_" not in repr(FigmaCredential(ref="FIGMA_PAT"))


def test_env_resolver_reads_at_call_time(monkeypatch):
    monkeypatch.setenv("FIGMA_PAT", REAL_LOOKING)
    assert EnvSecretResolver().resolve("FIGMA_PAT") == REAL_LOOKING
    monkeypatch.setenv("FIGMA_PAT", "figd_rotated_bBBBBBBBBBBBBBBBBBBBBBBBBB")
    assert EnvSecretResolver().resolve("FIGMA_PAT").endswith("BBB")


def test_env_resolver_missing_is_a_clear_error(monkeypatch):
    monkeypatch.delenv("FIGMA_PAT", raising=False)
    with pytest.raises(FigmaCredentialError, match="FIGMA_PAT"):
        EnvSecretResolver().resolve("FIGMA_PAT")


@pytest.mark.parametrize("text", [
    REAL_LOOKING,
    "figu_aB3dEfGhIjKlMnOpQrStUvWxYz0123456789",
    "1a2b3c4d-5e6f-7a8b-9c0d-1e2f3a4b5c6d",
])
def test_redact_catches_token_shapes(text):
    out = redact(f"Figma said: {text} (401)")
    assert text not in out
    assert "[figma-token-redacted]" in out


def test_redact_leaves_ordinary_text_alone():
    assert redact("frame 1:234 has no children") == "frame 1:234 has no children"


def test_looks_like_token():
    assert looks_like_token(REAL_LOOKING)
    assert not looks_like_token("FIGMA_PAT")
