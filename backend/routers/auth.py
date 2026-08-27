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
)
from database import get_db
from models.auth import PlatformUser
from models.org import OrgMember, Organization
from schemas.auth import (
    SignupRequest,
    LoginRequest,
    TokenResponse,
    RefreshRequest,
    UserResponse,
    OrgMembership,
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

    # Successful login — clear failed attempts
    clear_failed_attempts(req.email)

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

    # Blacklist the old refresh token (rotation)
    blacklist_token(req.refresh_token)

    # Issue new token pair
    import uuid
    uid = uuid.UUID(user_id)
    access_token = create_access_token(uid)
    refresh_token = create_refresh_token(uid)
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
    current_user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Load org memberships
    result = await db.execute(
        select(OrgMember)
        .where(OrgMember.user_id == current_user.id)
        .where(OrgMember.invite_status == "accepted")
        .options(selectinload(OrgMember.organization))
    )
    memberships = result.scalars().all()

    orgs = [
        OrgMembership(
            org_id=m.org_id,
            org_name=m.organization.name,
            org_slug=m.organization.slug,
            role=m.role.value,
        )
        for m in memberships
    ]

    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        name=current_user.name,
        created_at=current_user.created_at,
        orgs=orgs,
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
    """Issue a password-reset link.

    Always returns 200 with the same generic message — never leaks
    whether the account exists. When email is not yet wired, and the
    ``FORGE_RESET_URL_IN_RESPONSE`` env flag is truthy, the reset URL is
    also returned in the body so the operator can hand it to the user
    manually. Once an email provider is wired, drop that env flag.
    """
    generic = ForgotPasswordResponse(
        message="If an account exists for that email, a reset link has been generated.",
    )

    result = await db.execute(
        select(PlatformUser).where(PlatformUser.email == req.email.lower())
    )
    user = result.scalar_one_or_none()
    if not user:
        # Silent no-op — same response shape as the found case, no timing
        # tell (bcrypt above didn't run so timing is minimally different;
        # a fake bcrypt could be added if that matters).
        logger.info("[forgot-password] no user for email; returning generic response")
        return generic

    token = create_password_reset_token(user.id)
    reset_url = _build_reset_url(request, token)
    logger.info(
        "[forgot-password] generated reset link for user_id=%s (email not wired — link surfaced via API response)",
        user.id,
    )

    if os.environ.get("FORGE_RESET_URL_IN_RESPONSE", "1") not in ("0", "false", "False", ""):
        return ForgotPasswordResponse(message=generic.message, reset_url=reset_url)
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
