"""Tests for auth flow: signup, login, refresh, logout, lockout."""

import pytest
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient, ASGITransport

# Patch database before importing app
import sys
from unittest.mock import MagicMock

# Mock the database module
mock_db_module = MagicMock()
mock_db_module.get_db = AsyncMock()


@pytest.fixture
def anyio_backend():
    return "asyncio"


class TestPasswordValidation:
    """Test password strength validation."""

    def test_too_short(self):
        from auth import validate_password_strength
        assert validate_password_strength("Abc1") is not None

    def test_no_uppercase(self):
        from auth import validate_password_strength
        assert validate_password_strength("abcdefg1") is not None

    def test_no_lowercase(self):
        from auth import validate_password_strength
        assert validate_password_strength("ABCDEFG1") is not None

    def test_no_digit(self):
        from auth import validate_password_strength
        assert validate_password_strength("Abcdefgh") is not None

    def test_valid_password(self):
        from auth import validate_password_strength
        assert validate_password_strength("Abcdefg1") is None

    def test_strong_password(self):
        from auth import validate_password_strength
        assert validate_password_strength("MyStr0ngP@ss!") is None


class TestTokens:
    """Test JWT token creation and validation."""

    def test_create_and_decode_access_token(self):
        import uuid
        from auth import create_access_token, decode_token

        user_id = uuid.uuid4()
        token = create_access_token(user_id)
        payload = decode_token(token, expected_type="access")
        assert payload["sub"] == str(user_id)
        assert payload["type"] == "access"

    def test_create_and_decode_refresh_token(self):
        import uuid
        from auth import create_refresh_token, decode_token

        user_id = uuid.uuid4()
        token = create_refresh_token(user_id)
        payload = decode_token(token, expected_type="refresh")
        assert payload["sub"] == str(user_id)
        assert payload["type"] == "refresh"
        assert "jti" in payload

    def test_wrong_token_type_rejected(self):
        import uuid
        from auth import create_refresh_token, decode_token
        from fastapi import HTTPException

        user_id = uuid.uuid4()
        token = create_refresh_token(user_id)
        with pytest.raises(HTTPException) as exc_info:
            decode_token(token, expected_type="access")
        assert exc_info.value.status_code == 401

    def test_blacklisted_token_rejected(self):
        import uuid
        from auth import create_refresh_token, decode_token, blacklist_token
        from fastapi import HTTPException

        user_id = uuid.uuid4()
        token = create_refresh_token(user_id)
        blacklist_token(token)
        with pytest.raises(HTTPException) as exc_info:
            decode_token(token, expected_type="refresh")
        assert exc_info.value.status_code == 401


class TestLoginLockout:
    """Test account lockout after failed attempts."""

    def test_lockout_after_max_attempts(self):
        from auth import (
            check_login_attempts,
            record_failed_attempt,
            clear_failed_attempts,
            _login_attempts,
        )
        from fastapi import HTTPException

        email = "lockout-test@example.com"
        clear_failed_attempts(email)

        # Record max attempts
        for _ in range(5):
            record_failed_attempt(email)

        # Should now be locked out
        with pytest.raises(HTTPException) as exc_info:
            check_login_attempts(email)
        assert exc_info.value.status_code == 429

        # Cleanup
        clear_failed_attempts(email)

    def test_successful_login_clears_attempts(self):
        from auth import (
            check_login_attempts,
            record_failed_attempt,
            clear_failed_attempts,
        )

        email = "clear-test@example.com"
        record_failed_attempt(email)
        record_failed_attempt(email)

        clear_failed_attempts(email)

        # Should not raise
        check_login_attempts(email)
