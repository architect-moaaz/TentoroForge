"""SSO/OAuth endpoints — Google, Microsoft, Okta callback handlers."""

import uuid
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import create_access_token, create_refresh_token
from database import get_db
from models.auth import PlatformUser
from schemas.auth import TokenResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth/sso", tags=["sso"])

# OAuth provider configurations (loaded from env at runtime)
PROVIDERS = {
    "google": {
        "token_url": "https://oauth2.googleapis.com/token",
        "userinfo_url": "https://www.googleapis.com/oauth2/v2/userinfo",
        "env_client_id": "GOOGLE_CLIENT_ID",
        "env_client_secret": "GOOGLE_CLIENT_SECRET",
    },
    "microsoft": {
        "token_url": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        "userinfo_url": "https://graph.microsoft.com/v1.0/me",
        "env_client_id": "MICROSOFT_CLIENT_ID",
        "env_client_secret": "MICROSOFT_CLIENT_SECRET",
    },
    "okta": {
        "token_url": "{okta_domain}/oauth2/default/v1/token",
        "userinfo_url": "{okta_domain}/oauth2/default/v1/userinfo",
        "env_client_id": "OKTA_CLIENT_ID",
        "env_client_secret": "OKTA_CLIENT_SECRET",
    },
}


@router.get("/{provider}/callback", response_model=TokenResponse)
async def sso_callback(
    provider: str,
    code: str = Query(...),
    redirect_uri: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Handle OAuth callback — exchange code for token, upsert user, return JWT."""
    import os

    if provider not in PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unsupported provider: {provider}")

    config = PROVIDERS[provider]
    client_id = os.getenv(config["env_client_id"], "")
    client_secret = os.getenv(config["env_client_secret"], "")

    if not client_id or not client_secret:
        raise HTTPException(status_code=500, detail=f"{provider} SSO not configured")

    # Exchange code for access token
    token_url = config["token_url"]
    if provider == "okta":
        okta_domain = os.getenv("OKTA_DOMAIN", "")
        token_url = token_url.replace("{okta_domain}", okta_domain)

    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            token_url,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": client_id,
                "client_secret": client_secret,
            },
        )
        if token_resp.status_code != 200:
            logger.error("SSO token exchange failed: %s", token_resp.text)
            raise HTTPException(status_code=401, detail="SSO authentication failed")

        tokens = token_resp.json()
        access_token = tokens.get("access_token")

        # Fetch user info
        userinfo_url = config["userinfo_url"]
        if provider == "okta":
            okta_domain = os.getenv("OKTA_DOMAIN", "")
            userinfo_url = userinfo_url.replace("{okta_domain}", okta_domain)

        user_resp = await client.get(
            userinfo_url,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if user_resp.status_code != 200:
            raise HTTPException(status_code=401, detail="Failed to fetch user info")

        user_info = user_resp.json()

    # Extract user data based on provider
    email, name, external_id, avatar_url = _extract_user_info(provider, user_info)

    if not email:
        raise HTTPException(status_code=400, detail="Email not available from provider")

    # Upsert user
    result = await db.execute(
        select(PlatformUser).where(PlatformUser.email == email)
    )
    user = result.scalar_one_or_none()

    if user:
        # Update provider info
        user.auth_provider = provider
        user.external_id = external_id
        if avatar_url:
            user.avatar_url = avatar_url
    else:
        # Create new user
        user = PlatformUser(
            email=email,
            name=name or email.split("@")[0],
            auth_provider=provider,
            external_id=external_id,
            avatar_url=avatar_url,
            password_hash=None,  # SSO users don't have passwords
        )
        db.add(user)

    await db.commit()
    await db.refresh(user)

    jwt_access = create_access_token(user.id)
    jwt_refresh = create_refresh_token(user.id)
    return TokenResponse(access_token=jwt_access, refresh_token=jwt_refresh)


def _extract_user_info(
    provider: str, info: dict
) -> tuple[str | None, str | None, str | None, str | None]:
    """Extract email, name, external_id, avatar_url from provider user info."""
    if provider == "google":
        return (
            info.get("email"),
            info.get("name"),
            info.get("id"),
            info.get("picture"),
        )
    elif provider == "microsoft":
        return (
            info.get("mail") or info.get("userPrincipalName"),
            info.get("displayName"),
            info.get("id"),
            None,  # MS Graph requires separate endpoint for photo
        )
    elif provider == "okta":
        return (
            info.get("email"),
            info.get("name"),
            info.get("sub"),
            None,
        )
    return None, None, None, None
