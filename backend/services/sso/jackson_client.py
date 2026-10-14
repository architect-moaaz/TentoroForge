"""The platform's SAML bridge: BoxyHQ SAML Jackson, hosted once.

An application declared to sign in over SAML never speaks SAML itself: it
speaks OpenID Connect to Jackson (next-auth's `boxyhq-saml` provider), and
Jackson speaks SAML to the enterprise's identity provider. The enterprise's
metadata is registered here, per application (`tenant` = the project id,
`product` = "forge"), and what comes back is the client id and secret the
application's `SSO_<ID>_CLIENT_ID` / `SSO_<ID>_CLIENT_SECRET` hold, with
`SSO_<ID>_ISSUER` the bridge's own address. Jackson runs from
`docker-compose.prod.yml` under the `sso` profile and is reached by
`JACKSON_URL` with `JACKSON_API_KEY`; without them the bridge is not hosted,
and a SAML sign-in is said to be unconnected rather than guessed at.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

PRODUCT = "forge"


def configured(env: dict[str, str] | None = None) -> bool:
    env = env if env is not None else dict(os.environ)
    return bool(env.get("JACKSON_URL") and env.get("JACKSON_API_KEY"))


def bridge_url(env: dict[str, str] | None = None) -> str:
    env = env if env is not None else dict(os.environ)
    return str(env.get("JACKSON_URL") or "").rstrip("/")


def _call(method: str, path: str, body: dict[str, Any] | None, env: dict[str, str] | None = None) -> dict[str, Any]:
    env = env if env is not None else dict(os.environ)
    req = urllib.request.Request(bridge_url(env) + path, data=json.dumps(body).encode() if body is not None else None,
                                 method=method, headers={"Authorization": f"Api-Key {env.get('JACKSON_API_KEY', '')}",
                                                         "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            text = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"the SAML bridge answered {e.code}: {e.read().decode('utf-8', 'replace')[:200]}") from e
    try:
        return json.loads(text) if text else {}
    except ValueError:
        return {}


def connection_body(tenant: str, app_address: str, entry_id: str, *, metadata_xml: str = "", metadata_url: str = "",
                    name: str = "") -> dict[str, Any]:
    """What Jackson is told about one application's SAML connection. The
    redirect is the application's next-auth callback for the entry."""
    if not metadata_xml and not metadata_url:
        raise ValueError("the identity provider's SAML metadata (XML or its URL) is needed")
    callback = f"{app_address.rstrip('/')}/api/auth/callback/{entry_id}"
    body: dict[str, Any] = {"tenant": tenant, "product": PRODUCT, "name": name or f"{tenant}:{entry_id}",
                            "defaultRedirectUrl": callback, "redirectUrl": [callback]}
    if metadata_xml:
        body["rawMetadata"] = metadata_xml
    else:
        body["metadataUrl"] = metadata_url
    return body


def register_saml(tenant: str, app_address: str, entry_id: str, *, metadata_xml: str = "", metadata_url: str = "",
                  name: str = "", env: dict[str, str] | None = None) -> dict[str, str]:
    """Register the enterprise's SAML identity provider for one application.
    Returns the three values the application's names hold."""
    if not configured(env):
        raise RuntimeError("the SAML bridge is not hosted here: set JACKSON_URL and JACKSON_API_KEY on the platform "
                           "(docker compose --profile sso)")
    out = _call("POST", "/api/v1/sso", connection_body(tenant, app_address, entry_id, metadata_xml=metadata_xml,
                                                        metadata_url=metadata_url, name=name), env)
    client_id = str(out.get("clientID") or out.get("clientId") or "")
    client_secret = str(out.get("clientSecret") or "")
    if not client_id:
        raise RuntimeError("the SAML bridge registered nothing (no client id came back)")
    from services.blueprint.projection import sso_secret_names
    names = sso_secret_names(entry_id)
    return {names["issuerKey"]: bridge_url(env), names["clientIdKey"]: client_id, names["clientSecretKey"]: client_secret}


__all__ = ["PRODUCT", "bridge_url", "configured", "connection_body", "register_saml"]
