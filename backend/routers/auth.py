"""Auth endpoints: signup, login, refresh, logout, me, forgot/reset password."""

import logging
import os
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from auth import (
    hash_password,
    verify_password,
    validate_password_strength,
    create_access_token,
    create_refresh_token,
    create_password_reset_token,
    decode_token,
    blacklist_token,
    check_login_attempts,
    record_failed_attempt,
    clear_failed_attempts,
    get_current_user,
    DISABLED_MESSAGE,
)
from database import get_db
from models.auth import PlatformUser
from models.org import OrgMember, Organization
from platform_admin import record_sign_in
from schemas.auth import (
    SignupRequest,
    LoginRequest,
    TokenResponse,
    RefreshRequest,
    UserResponse,
    OrgMembership,
    ImpersonatedBy,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    ResetPasswordRequest,
    ResetPasswordResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/signup", response_model=TokenResponse, status_code=201)
async def signup(req: SignupRequest, db: AsyncSession = Depends(get_db)):
    # Validate password strength
    password_error = validate_password_strength(req.password)
    if password_error:
        raise HTTPException(status_code=400, detail=password_error)

    # Check if email already exists
    existing = await db.execute(
        select(PlatformUser).where(PlatformUser.email == req.email)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")

    user = PlatformUser(
        email=req.email,
        name=req.name,
        password_hash=hash_password(req.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    await record_sign_in(user, db)

    access_token = create_access_token(user.id)
    refresh_token = create_refresh_token(user.id)
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    # Check for account lockout
    check_login_attempts(req.email)

    result = await db.execute(
        select(PlatformUser).where(PlatformUser.email == req.email)
    )
    user = result.scalar_one_or_none()
    if not user or not verify_password(req.password, user.password_hash):
        record_failed_attempt(req.email)
        raise HTTPException(status_code=401, detail="Invalid email or password")
    # A disabled login is refused with its own words, and the attempt is not
    # a failed one: the password was right.
    if user.disabled_at is not None:
        raise HTTPException(status_code=401, detail=DISABLED_MESSAGE)

    # Successful login — clear failed attempts
    clear_failed_attempts(req.email)
    await record_sign_in(user, db)

    access_token = create_access_token(user.id)
    refresh_token = create_refresh_token(user.id)
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(req: RefreshRequest, db: AsyncSession = Depends(get_db)):
    """Exchange a refresh token for a new access + refresh token pair (rotation)."""
    payload = decode_token(req.refresh_token, expected_type="refresh")
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    # THE PERSON IS LOOKED UP AGAIN. A refresh used to mint a new pair for
    # whatever id the old token carried; a login disabled or deleted in the
    # meantime would have lived on for another week.
    user = await db.get(PlatformUser, uuid.UUID(user_id))
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    if user.disabled_at is not None:
        raise HTTPException(status_code=401, detail=DISABLED_MESSAGE)

    # Blacklist the old refresh token (rotation)
    blacklist_token(req.refresh_token)

    # Issue new token pair
    access_token = create_access_token(user.id)
    refresh_token = create_refresh_token(user.id)
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/logout", status_code=204)
async def logout(
    current_user: PlatformUser = Depends(get_current_user),
):
    """Logout — blacklist is handled client-side by clearing tokens.
    If a refresh token is provided in future, it can be blacklisted here."""
    return None


@router.get("/me", response_model=UserResponse)
async def get_me(
    request: Request,
    current_user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Load org memberships — a removed organisation is not one of theirs any
    # more; a blocked one is listed with its status, so the UI can say why.
    result = await db.execute(
        select(OrgMember)
        .where(OrgMember.user_id == current_user.id)
        .where(OrgMember.invite_status == "accepted")
        .options(selectinload(OrgMember.organization))
    )
    memberships = [m for m in result.scalars().all() if not m.organization.is_removed]

    orgs = [
        OrgMembership(
            org_id=m.org_id,
            org_name=m.organization.name,
            org_slug=m.organization.slug,
            role=m.role.value,
            status=m.organization.status,
        )
        for m in memberships
    ]

    actor = getattr(request.state, "actor", None)
    impersonated = getattr(request.state, "impersonated_by", None)
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        name=current_user.name,
        created_at=current_user.created_at,
        orgs=orgs,
        platform_role=current_user.platform_role,
        disabled=current_user.disabled_at is not None,
        impersonated_by=ImpersonatedBy(id=actor.id, email=actor.email) if impersonated and actor else None,
    )


# --------------------------------------------------------------------------- #
# Password reset
# --------------------------------------------------------------------------- #


def _build_reset_url(request: Request, token: str) -> str:
    """Prefer FORGE_APP_BASE_URL (set in prod to the canonical frontend
    origin) over the request's own origin, so that reset links land on
    the public URL even when the request came in on a different host
    (e.g. localhost, an internal LB address)."""
    base = os.environ.get("FORGE_APP_BASE_URL", "").rstrip("/")
    if not base:
        base = str(request.base_url).rstrip("/")
    return f"{base}/reset-password?token={token}"


@router.post("/forgot-password", response_model=ForgotPasswordResponse)
async def forgot_password(
    req: ForgotPasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Send a password-reset link to the account's own address.

    Always returns 200 with the same generic message — never leaks whether
    the account exists. The link goes only to the inbox: anyone can ask for
    any address, so a link in the answer was a takeover of any login,
    super admins included (audit, 2026-11-01). Where the platform sends no
    mail, a super admin issues a link from the cockpit
    (`POST /api/admin/people/{id}/reset-link`); on a development platform
    the mail, link and all, is written to the log.
    """
    generic = ForgotPasswordResponse(
        message="If an account exists for that email, a reset link has been sent to it.",
    )

    result = await db.execute(
        select(PlatformUser).where(PlatformUser.email == req.email.lower())
    )
    user = result.scalar_one_or_none()
    if not user:
        logger.info("[forgot-password] no user for email; returning generic response")
        return generic

    token = create_password_reset_token(user.id)
    reset_url = _build_reset_url(request, token)
    from services.email_service import send_email

    sent = await send_email(user.email, "password_reset", {"reset_url": reset_url, "name": user.name or ""})
    logger.info("[forgot-password] reset link for user_id=%s %s", user.id, "sent" if sent else "NOT sent (no mail provider)")

    return generic


@router.post("/reset-password", response_model=ResetPasswordResponse)
async def reset_password(
    req: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """Consume a reset token and set a new password.

    Token is single-use: on success it's added to the blacklist so the
    same link can't reset twice. Password must pass the strength gate.
    """
    # Validate strength BEFORE decode so a weak-password error doesn't
    # burn the token — the user can retry with the same link.
    strength_error = validate_password_strength(req.new_password)
    if strength_error:
        raise HTTPException(status_code=400, detail=strength_error)

    payload = decode_token(req.token, expected_type="password_reset")
    user_id_str = payload.get("sub")
    if not user_id_str:
        raise HTTPException(status_code=400, detail="Invalid reset token")
    try:
        user_id = uuid.UUID(user_id_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid reset token")

    result = await db.execute(select(PlatformUser).where(PlatformUser.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        # Token verified but user vanished — unlikely but treat as invalid.
        raise HTTPException(status_code=400, detail="Invalid reset token")

    user.password_hash = hash_password(req.new_password)
    await db.commit()

    # Single-use: burn the token so the same link can't reset again.
    blacklist_token(req.token)
    # Also clear any failed-attempt counter so the user isn't locked out
    # right after a successful reset.
    clear_failed_attempts(user.email)

    logger.info("[reset-password] password updated for user_id=%s", user_id)
    return ResetPasswordResponse(message="Password updated. You can now log in.")
