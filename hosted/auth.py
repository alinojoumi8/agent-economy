"""Shared value objects and policy used by hosted authentication."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Sequence

from hosted.security import (
    SecurityValidationError,
    build_csrf_cookie,
    build_session_cookie,
    parse_display_name,
    parse_email,
    parse_opaque_token,
    validate_password_hash,
)


def _utc(value: datetime, field: str = "timestamp") -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise SecurityValidationError(f"{field} must be timezone-aware")
    try:
        offset = value.utcoffset()
    except (OverflowError, ValueError) as exc:
        raise SecurityValidationError(f"{field} is invalid") from exc
    if offset is None:
        raise SecurityValidationError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _record_id(value: object, field: str) -> str:
    if not isinstance(value, str) or value != value.strip() or not (1 <= len(value) <= 128):
        raise SecurityValidationError(f"{field} must be a bounded identifier")
    if any(ord(char) < 33 or ord(char) > 126 for char in value):
        raise SecurityValidationError(f"{field} must be printable ASCII without spaces")
    return value


@dataclass(frozen=True)
class UserRecord:
    user_id: str
    email: str
    display_name: str
    password_hash: str
    created_at: datetime
    disabled_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "user_id", _record_id(self.user_id, "user_id"))
        object.__setattr__(self, "email", parse_email(self.email))
        object.__setattr__(self, "display_name", parse_display_name(self.display_name))
        object.__setattr__(self, "password_hash", validate_password_hash(self.password_hash))
        created = _utc(self.created_at, "created_at")
        object.__setattr__(self, "created_at", created)
        if self.disabled_at is not None:
            disabled = _utc(self.disabled_at, "disabled_at")
            if disabled < created:
                raise SecurityValidationError("disabled_at predates user creation")
            object.__setattr__(self, "disabled_at", disabled)


@dataclass(frozen=True)
class SessionCredentials:
    session_token: str
    csrf_token: str
    expires_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "session_token", parse_opaque_token(self.session_token))
        object.__setattr__(self, "csrf_token", parse_opaque_token(self.csrf_token))
        if self.session_token == self.csrf_token:
            raise SecurityValidationError("session and CSRF tokens must be distinct")
        object.__setattr__(self, "expires_at", _utc(self.expires_at, "expires_at"))

    @property
    def session_cookie(self) -> str:
        return build_session_cookie(self.session_token)

    @property
    def csrf_cookie(self) -> str:
        return build_csrf_cookie(self.csrf_token)


@dataclass(frozen=True)
class LoginThrottlePolicy:
    max_failures: int = 5
    window: timedelta = timedelta(minutes=15)

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_failures, bool)
            or not isinstance(self.max_failures, int)
            or not (1 <= self.max_failures <= 20)
        ):
            raise SecurityValidationError("max_failures must be an integer from 1 to 20")
        if not isinstance(self.window, timedelta) or not (
            timedelta(seconds=30) <= self.window <= timedelta(hours=24)
        ):
            raise SecurityValidationError("throttle window must be 30 seconds to 24 hours")

    def retry_after_seconds(
        self, failure_times: Sequence[datetime], now: datetime
    ) -> int:
        current = _utc(now, "now")
        boundary = current - self.window
        recent = sorted(
            timestamp
            for value in failure_times
            if boundary < (timestamp := _utc(value, "failure timestamp")) <= current
        )
        if len(recent) < self.max_failures:
            return 0
        lock_started = recent[-self.max_failures]
        return max(0, math.ceil((lock_started + self.window - current).total_seconds()))


class AuthFailure(Exception):
    """A stable, secret-free authentication-domain failure."""

    def __init__(self, code: str, *, retry_after_seconds: int = 0) -> None:
        self.code = _record_id(code, "auth failure code")
        self.retry_after_seconds = max(0, int(retry_after_seconds))
        super().__init__(code)
