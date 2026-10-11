"""Connect the application's sign-in to an identity provider.

"Connect sign-in to Microsoft 365", "let people sign in with Google",
"Okta over SAML": one `auth` integration row `serves: sign_in` with the
provider's secret NAMES (`SSO_<ID>_ISSUER`, `SSO_<ID>_CLIENT_ID`,
`SSO_<ID>_CLIENT_SECRET`) and one `security.signIn.sso` entry, projected
into the app; the reply says the redirect address to register at the
provider and the names still unset. SAML speaks to the platform's bridge
(BoxyHQ Jackson), so the application only ever speaks OpenID Connect.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

SERVES = "sign_in"
FROM_KEY = ""
#: The names are per ENTRY (`SSO_<ID>_…`): any complete triple is a
#: connection, so two Okta tenants can live side by side.
FLEXIBLE_NAMES = True


@dataclass(frozen=True)
class SignInService:
    name: str
    provider: str          # entra | google | okta | oidc | saml
    kind: str              # oidc | saml
    words: tuple[str, ...]
    issuer_hint: str
    caveat: str = ""


SERVICES: tuple[SignInService, ...] = (
    SignInService("Microsoft 365", "entra", "oidc",
                  ("microsoft", "entra", "azure ad", "azure active directory", "office 365", "m365", "microsoft 365"),
                  "https://login.microsoftonline.com/<tenant id>/v2.0", "Groups arrive as object ids unless the app registration emits group names."),
    SignInService("Google Workspace", "google", "oidc", ("google", "gsuite", "g suite", "google workspace"),
                  "https://accounts.google.com", "Google sends the organisation's domain (`hd`), not groups."),
    SignInService("Okta", "okta", "oidc", ("okta",), "https://<org>.okta.com"),
    SignInService("SAML", "saml", "saml",
                  ("saml", "adfs", "ping", "pingfederate", "onelogin", "shibboleth", "identity provider", "idp"),
                  "the platform's SAML bridge", "The enterprise's SAML metadata is uploaded to the platform's bridge; the app speaks OpenID Connect to it."),
    SignInService("OpenID Connect", "oidc", "oidc", ("oidc", "openid", "open id", "auth0", "keycloak", "cognito"),
                  "the issuer's address (with /.well-known/openid-configuration)"),
)
CHOICES: tuple[str, ...] = tuple(s.name for s in SERVICES)
#: The variable whose presence means the provider carries sign-in live.
LIVE_KEY: dict[str, str] = {s.provider: f"SSO_{s.provider.upper()}_CLIENT_ID" for s in SERVICES}


class NoSignInAdapter(LookupError):
    """The service named is not one the application can sign people in through."""


def names_for(entry_id: str) -> list[str]:
    from services.blueprint.projection import sso_secret_names
    n = sso_secret_names(entry_id)
    return [n["issuerKey"], n["clientIdKey"], n["clientSecretKey"]]


def keys_for(provider: str) -> list[str]:
    svc = next((s for s in SERVICES if s.provider == provider), None)
    return names_for(svc.provider) if svc else []


def complete_triples(refs: list[str]) -> list[str]:
    """The entry ids whose three names are all among `refs`."""
    import re
    ids: dict[str, set[str]] = {}
    for r in refs:
        m = re.match(r"^SSO_([A-Z0-9_]+?)_(ISSUER|CLIENT_ID|CLIENT_SECRET)$", str(r))
        if m:
            ids.setdefault(m.group(1), set()).add(m.group(2))
    return sorted(k for k, v in ids.items() if v == {"ISSUER", "CLIENT_ID", "CLIENT_SECRET"})


def service_for(said: str) -> SignInService | None:
    text = (said or "").lower()
    # Only a sentence about SIGNING IN is this adapter's: "connect it to our
    # Microsoft 365" alone is mail (the email adapter is tried first).
    if not any(w in text for w in ("sign in", "sign-in", "signin", "log in", "login", "sso", "single sign", "saml", "identity provider", "idp", "oidc", "openid")):
        return None
    # THE PROTOCOL WINS: "Okta over SAML" is a SAML connection (through the
    # platform's bridge) whoever the identity provider is.
    saml = next(s for s in SERVICES if s.provider == "saml")
    if any(w in text for w in saml.words if w != "identity provider" and w != "idp"):
        return saml
    best: SignInService | None = None
    best_len = 0
    for svc in SERVICES:
        for word in svc.words:
            if word in text and len(word) > best_len:
                best, best_len = svc, len(word)
    return best


def declared(doc: dict) -> list[dict]:
    return [row for row in doc.get("integrations") or [] if isinstance(row, dict)
            and str(row.get("serves") or "") == SERVES
            and str(row.get("status") or "").upper() not in ("DEPRECATED", "REMOVED")]


def _entry_id(svc: Any, provider: str) -> str:
    """The entry's id: the provider's name, or `<provider>_2` when one exists."""
    existing = {str(e.get("id")) for e in (((svc.doc.get("security") or {}).get("signIn") or {}).get("sso") or []) if isinstance(e, dict)}
    if provider not in existing:
        return provider
    n = 2
    while f"{provider}_{n}" in existing:
        n += 1
    return f"{provider}_{n}"


def connect(svc: Any, *, service: str, output_dir: str | None = None, reasoning: Any = None) -> dict[str, Any]:
    from services.blueprint.ids import integration_key
    from services.llm_client import tell
    from services.smith.section_change import record_requirement
    chosen = service_for(service)
    if chosen is None:
        raise NoSignInAdapter(service)
    req = record_requirement(svc, f"People sign in through {chosen.name}.", owner="security")
    entry_id = _entry_id(svc, chosen.provider)
    names = names_for(entry_id)
    before = svc.snapshot()
    row = svc.upsert("integrations", {
        "name": f"{chosen.name} sign-in" if entry_id == chosen.provider else f"{chosen.name} sign-in ({entry_id})",
        "kind": "auth", "provider": chosen.provider, "secretRefs": names, "serves": SERVES, "status": "APPROVED",
        "requirements": [str(req.get("id"))] if req.get("id") else [],
    }, natural_key=integration_key(f"{chosen.name} sign-in {entry_id}"))
    sec = svc.doc.setdefault("security", {})
    si = sec.setdefault("signIn", {})
    si.setdefault("password", True)
    si.setdefault("magicLink", False)
    sso = si.setdefault("sso", [])
    sso.append({"id": entry_id, "name": chosen.name, "kind": chosen.kind, "provider": chosen.provider,
                "integration": str(row.get("id") or ""), "domains": [], "provisioning": "just_in_time"})
    svc.save()
    svc.commit(user_request=f"connect sign-in to {service}".strip(),
               smith_interpretation=f"people sign in through {chosen.name}; live once {', '.join(names)} are set",
               before=before, affected=[str(row.get("id") or "")])
    tell(reasoning, f"Recorded {chosen.name} as a way people sign in to this application.", "step")
    files: list[str] = []
    set_keys: set[str] = set()
    if output_dir:
        from pathlib import Path

        from services.blueprint.projection import project_integrations, project_sign_in
        app_root = Path(output_dir) / "app"
        if app_root.is_dir():
            files = list(project_integrations(svc.doc, app_root).get("files") or [])
            files += list(project_sign_in(svc.doc, app_root).get("files") or [])
        try:
            from services.platform_secrets import keys_set_for
            set_keys = set(keys_set_for(output_dir, names))
        except Exception:  # noqa: BLE001 — no store reachable: nothing is set
            set_keys = set()
    return {"applied": True, "integration": str(row.get("id") or ""), "name": chosen.name, "provider": chosen.provider,
            "kind": chosen.kind, "entry": entry_id, "secrets": names, "set": sorted(set_keys),
            "missing": [k for k in names if k not in set_keys], "connected": names[1] in set_keys,
            "issuer_hint": chosen.issuer_hint, "caveat": chosen.caveat, "edited_paths": files}


def summarise(out: dict[str, Any]) -> str:
    missing = ", ".join(out.get("missing") or [])
    entry = out.get("entry")
    said = (f"People can sign in through {out.get('name')}. "
            + ("It is live. " if out.get("connected") else f"Set {missing} under Settings → Integrations to make it live (the issuer is {out.get('issuer_hint')}); until then the sign-in screen says it is not connected. ")
            + f"Register this redirect address at {out.get('name')}: `<the application's address>/api/auth/callback/{entry}` "
            "(the published address once it is published; a preview sits behind the platform, so a provider cannot reach it).")
    if out.get("caveat"):
        said += f" {out['caveat']}"
    return said


def refusal(said: str, doc: dict) -> tuple[str, list[str]]:
    return (f"I cannot sign people in through {said!r}: this application can sign people in through "
            f"{', '.join(CHOICES[:-1])} or any OpenID Connect issuer. Name one.",
            [f"Sign in through {c}" for c in CHOICES[:3]])


def run(output_dir: str, *, service: str, reasoning: Any = None) -> dict[str, Any]:
    from services.blueprint.service import BlueprintService
    from services.smith.secrets_scrub import scrub
    try:
        svc = BlueprintService.load(output_dir=str(output_dir))
    except FileNotFoundError:
        return {"applied": False, "edited_paths": [], "reason": "this project has no Blueprint yet.", "options": []}
    try:
        out = connect(svc, service=service, output_dir=str(output_dir), reasoning=reasoning)
    except NoSignInAdapter:
        why, options = refusal(scrub(service), svc.doc)
        return {"applied": False, "edited_paths": [], "reason": why, "options": options}
    except Exception as exc:  # noqa: BLE001
        logger.exception("[smith] connect sign-in failed for %r", service)
        return {"applied": False, "edited_paths": [], "reason": f"{type(exc).__name__}: {exc}", "options": []}
    return {"applied": True, "edited_paths": list(out.get("edited_paths") or []), "diff_summary": summarise(out),
            "reason": "", "options": [], **{k: v for k, v in out.items() if k != "edited_paths"}}


__all__ = ["CHOICES", "FLEXIBLE_NAMES", "LIVE_KEY", "SERVES", "SERVICES", "complete_triples", "connect", "declared",
           "keys_for", "names_for", "refusal", "run", "service_for", "summarise"]
