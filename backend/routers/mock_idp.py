"""A mock identity provider, on the platform, for proving an application's
sign-in through a provider on a bench.

A real provider cannot reach a bench copy (it sits behind the platform), and
a check must never carry a real tenant's client secret. This issuer speaks
OpenID Connect with discovery, PKCE and RS256 id tokens, and also answers
BoxyHQ Jackson's OAuth paths (`/api/oauth/…`), so an application declared
to sign in over SAML — which speaks OIDC to the bridge — is proven the same
way. It knows no accounts: the check REGISTERS the claims of the next sign-in
for a client id (`POST /next`), then drives the application's own sign-in
through it. An application trusts this issuer only when its `SSO_<ID>_ISSUER`
is set to it, which only a check's bench environment does.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import time
from typing import Any

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

router = APIRouter(prefix="/dev/mock-idp", tags=["mock-idp"])

_KEY: dict[str, Any] = {}
_NEXT: dict[str, dict[str, Any]] = {}
_CODES: dict[str, dict[str, Any]] = {}
_TOKENS: dict[str, dict[str, Any]] = {}
DEFAULT_CLAIMS = {"sub": "mock-person", "email": "person@example.com", "name": "Mock Person"}


def _key() -> dict[str, Any]:
    if not _KEY:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption()).decode()
        numbers = private.public_key().public_numbers()
        b64 = lambda n, length: base64.urlsafe_b64encode(n.to_bytes(length, "big")).rstrip(b"=").decode()  # noqa: E731
        _KEY.update({"pem": pem, "kid": secrets.token_hex(8),
                     "jwk": {"kty": "RSA", "use": "sig", "alg": "RS256", "n": b64(numbers.n, 256), "e": b64(numbers.e, 3)}})
        _KEY["jwk"]["kid"] = _KEY["kid"]
    return _KEY


def issuer() -> str:
    from services.app_reporting import internal_url
    return internal_url() + "/dev/mock-idp"


def register_next(client_id: str, claims: dict[str, Any]) -> None:
    """The claims the next sign-in for `client_id` carries."""
    _NEXT[client_id] = {**DEFAULT_CLAIMS, **claims}


@router.post("/next")
async def next_sign_in(body: dict[str, Any]) -> dict[str, Any]:
    client_id = str(body.get("client_id") or "")
    if not client_id:
        raise HTTPException(400, "client_id")
    register_next(client_id, dict(body.get("claims") or {}))
    return {"ok": True}


@router.get("/.well-known/openid-configuration")
async def discovery() -> dict[str, Any]:
    iss = issuer()
    return {"issuer": iss, "authorization_endpoint": f"{iss}/authorize", "token_endpoint": f"{iss}/token",
            "userinfo_endpoint": f"{iss}/userinfo", "jwks_uri": f"{iss}/jwks",
            "response_types_supported": ["code"], "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": ["RS256"], "scopes_supported": ["openid", "email", "profile"],
            "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post"],
            "code_challenge_methods_supported": ["S256"], "claims_supported": ["sub", "email", "name", "groups", "hd"]}


@router.get("/jwks")
async def jwks() -> dict[str, Any]:
    return {"keys": [_key()["jwk"]]}


def _authorize(params: dict[str, str]) -> RedirectResponse:
    client_id = params.get("client_id") or ""
    redirect_uri = params.get("redirect_uri") or ""
    if not client_id or not redirect_uri:
        raise HTTPException(400, "client_id and redirect_uri")
    code = secrets.token_urlsafe(24)
    _CODES[code] = {"claims": _NEXT.pop(client_id, dict(DEFAULT_CLAIMS)), "client_id": client_id, "redirect_uri": redirect_uri,
                    "nonce": params.get("nonce") or "", "challenge": params.get("code_challenge") or "",
                    "method": params.get("code_challenge_method") or "", "at": time.time()}
    sep = "&" if "?" in redirect_uri else "?"
    state = params.get("state") or ""
    return RedirectResponse(f"{redirect_uri}{sep}code={code}" + (f"&state={state}" if state else ""), status_code=302)


@router.get("/authorize")
async def authorize(request: Request) -> RedirectResponse:
    return _authorize(dict(request.query_params))


def _id_token(claims: dict[str, Any], client_id: str, nonce: str) -> str:
    from jose import jwt
    now = int(time.time())
    payload = {**claims, "iss": issuer(), "aud": client_id, "iat": now, "exp": now + 600}
    if nonce:
        payload["nonce"] = nonce
    k = _key()
    return jwt.encode(payload, k["pem"], algorithm="RS256", headers={"kid": k["kid"]})


async def _token(request: Request) -> JSONResponse:
    form = await request.form()
    code = str(form.get("code") or "")
    grant = _CODES.pop(code, None)
    if not grant or time.time() - grant["at"] > 300:
        return JSONResponse({"error": "invalid_grant"}, status_code=400)
    client_id = str(form.get("client_id") or "")
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("basic "):
        try:
            client_id = base64.b64decode(auth[6:]).decode().split(":", 1)[0]
        except Exception:  # noqa: BLE001
            pass
    if client_id and client_id != grant["client_id"]:
        return JSONResponse({"error": "invalid_client"}, status_code=401)
    if grant["challenge"]:
        verifier = str(form.get("code_verifier") or "")
        digest = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        if grant["method"] == "S256" and digest != grant["challenge"]:
            return JSONResponse({"error": "invalid_grant", "error_description": "PKCE"}, status_code=400)
    access = secrets.token_urlsafe(24)
    _TOKENS[access] = grant["claims"]
    return JSONResponse({"access_token": access, "token_type": "Bearer", "expires_in": 600, "scope": "openid email profile",
                         "id_token": _id_token(grant["claims"], grant["client_id"], grant["nonce"])})


@router.post("/token")
async def token(request: Request) -> JSONResponse:
    return await _token(request)


def _userinfo(request: Request) -> dict[str, Any]:
    auth = request.headers.get("authorization") or ""
    claims = _TOKENS.get(auth[7:]) if auth.lower().startswith("bearer ") else None
    if claims is None:
        raise HTTPException(401, "bearer")
    return claims


@router.get("/userinfo")
async def userinfo(request: Request) -> dict[str, Any]:
    return _userinfo(request)


# BoxyHQ Jackson's OAuth paths: an application declared to sign in over SAML
# speaks OIDC to the bridge at these, and is proven against them here.
@router.get("/api/oauth/authorize")
async def jackson_authorize(request: Request) -> RedirectResponse:
    return _authorize(dict(request.query_params))


@router.post("/api/oauth/token")
async def jackson_token(request: Request) -> JSONResponse:
    return await _token(request)


@router.get("/api/oauth/userinfo")
async def jackson_userinfo(request: Request) -> dict[str, Any]:
    c = _userinfo(request)
    # Jackson's profile: id, email, firstName, lastName, roles/groups.
    name = str(c.get("name") or "")
    return {"id": c.get("sub"), "email": c.get("email"), "firstName": name.split(" ")[0], "lastName": " ".join(name.split(" ")[1:]),
            "groups": c.get("groups") or [], "roles": c.get("groups") or []}


__all__ = ["DEFAULT_CLAIMS", "issuer", "register_next", "router"]
