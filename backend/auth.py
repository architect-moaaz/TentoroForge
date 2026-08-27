"""JWT authentication utilities with refresh tokens, blacklist, and account lockout."""

import re
import uuid
import time
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import (
    SECRET_KEY,
    JWT_ALGORITHM,
    JWT_ACCESS_EXPIRE_MINUTES,
    JWT_REFRESH_EXPIRE_DAYS,
    MAX_LOGIN_ATTEMPTS,
    LOCKOUT_DURATION_MINUTES,
)
from database import get_db
from models.auth import PlatformUser

logger = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()

# In-memory token blacklist (for production, use Redis)
_token_blacklist: set[str] = set()
_blacklist_expiry: dict[str, float] = {}

# In-memory login attempt tracker (for production, use Redis)
_login_attempts: dict[str, list[float]] = defaultdict(list)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def validate_password_strength(password: str) -> str | None:
    """Validate password strength. Returns error message or None if valid."""
    if len(password) < 8:
        return "Password must be at least 8 characters long"
    if not re.search(r"[A-Z]", password):
        return "Password must contain at least one uppercase letter"
    if not re.search(r"[a-z]", password):
        return "Password must contain at least one lowercase letter"
    if not re.search(r"\d", password):
        return "Password must contain at least one digit"
    return None


def create_access_token(user_id: uuid.UUID, org_id: uuid.UUID | None = None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=JWT_ACCESS_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "exp": expire,
        "type": "access",
    }
    if org_id:
        payload["org_id"] = str(org_id)
    return jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: uuid.UUID) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=JWT_REFRESH_EXPIRE_DAYS)
    payload = {
        "sub": str(user_id),
        "exp": expire,
        "type": "refresh",
        "jti": str(uuid.uuid4()),  # unique token ID for blacklisting
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGORITHM)


# Password-reset token TTL. Short — a reset link found in an old email
# should not be indefinitely usable.
PASSWORD_RESET_EXPIRE_MINUTES = 30


def create_password_reset_token(user_id: uuid.UUID) -> str:
    """Signed JWT for the forgot-password → reset flow. ``jti`` lets us
    blacklist a used token so the same link can't reset twice."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=PASSWORD_RESET_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "exp": expire,
        "type": "password_reset",
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_token(token: str, expected_type: str = "access") -> dict:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    # Check token type
    if payload.get("type") != expected_type:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Expected {expected_type} token",
        )

    # Check blacklist
    jti = payload.get("jti")
    if jti and jti in _token_blacklist:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked",
        )

    return payload


def blacklist_token(token: str) -> None:
    """Add a token to the blacklist."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])
        jti = payload.get("jti")
        if jti:
            _token_blacklist.add(jti)
            _blacklist_expiry[jti] = payload.get("exp", time.time() + 86400)
    except JWTError:
        pass  # Token already invalid, no need to blacklist

    _cleanup_blacklist()


def _cleanup_blacklist():
    """Remove expired tokens from blacklist."""
    now = time.time()
    expired = [jti for jti, exp in _blacklist_expiry.items() if exp < now]
    for jti in expired:
        _token_blacklist.discard(jti)
        _blacklist_expiry.pop(jti, None)


# ---------------------------------------------------------------------------
# Account lockout
# ---------------------------------------------------------------------------

def check_login_attempts(email: str) -> None:
    """Check if account is locked due to too many failed attempts."""
    now = time.time()
    cutoff = now - (LOCKOUT_DURATION_MINUTES * 60)

    # Clean old attempts
    _login_attempts[email] = [t for t in _login_attempts[email] if t > cutoff]

    if len(_login_attempts[email]) >= MAX_LOGIN_ATTEMPTS:
        remaining = int(LOCKOUT_DURATION_MINUTES - (now - _login_attempts[email][0]) / 60)
        logger.warning("Account locked for %s — %d minutes remaining", email, remaining)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Account temporarily locked. Try again in {max(1, remaining)} minutes.",
        )


def record_failed_attempt(email: str) -> None:
    _login_attempts[email].append(time.time())


def clear_failed_attempts(email: str) -> None:
    _login_attempts.pop(email, None)


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> PlatformUser:
    """FastAPI dependency — extracts and validates the current user from JWT."""
    payload = decode_token(credentials.credentials, expected_type="access")
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    result = await db.execute(
        select(PlatformUser).where(PlatformUser.id == uuid.UUID(user_id))
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user
