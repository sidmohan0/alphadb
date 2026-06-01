"""Lightweight signed-cookie dashboard access gate."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from alphadb.config import Settings


class DashboardAuthError(ValueError):
    """Raised when dashboard auth configuration or tokens are invalid."""


class CookieController(Protocol):
    def get(self, name: str) -> str | None: ...

    def set(self, name: str, value: str, *, max_age: int) -> None: ...

    def remove(self, name: str) -> None: ...


@dataclass(frozen=True)
class DashboardAuthConfig:
    pin: str | None
    cookie_secret: str | None
    cookie_ttl_seconds: int
    cookie_name: str

    @classmethod
    def from_settings(cls, settings: Settings) -> DashboardAuthConfig:
        return cls(
            pin=settings.dashboard_pin,
            cookie_secret=settings.dashboard_cookie_secret,
            cookie_ttl_seconds=settings.dashboard_cookie_ttl_seconds,
            cookie_name=settings.dashboard_cookie_name,
        )

    @property
    def enabled(self) -> bool:
        return bool(self.pin)

    def validate(self) -> DashboardAuthConfig:
        if not self.enabled:
            return self
        if self.pin is None or not (self.pin.isdigit() and len(self.pin) == 4):
            raise DashboardAuthError("dashboard PIN must be exactly four digits")
        if not self.cookie_secret:
            raise DashboardAuthError("dashboard cookie secret is required when dashboard PIN is set")
        if self.cookie_ttl_seconds <= 0:
            raise DashboardAuthError("dashboard cookie TTL must be positive")
        if not self.cookie_name:
            raise DashboardAuthError("dashboard cookie name must not be empty")
        return self


@dataclass(frozen=True)
class DashboardAccessDecision:
    authenticated: bool
    reason: str
    remember_token: str | None = None


def _now() -> datetime:
    return datetime.now(UTC)


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _canonical_payload(payload: dict[str, int]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _signature(secret: str, payload: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
    return _b64encode(digest)


def create_remember_token(
    config: DashboardAuthConfig,
    *,
    issued_at: datetime | None = None,
) -> str:
    config.validate()
    if not config.cookie_secret:
        raise DashboardAuthError("dashboard cookie secret is required")
    issued = issued_at or _now()
    expires = issued + timedelta(seconds=config.cookie_ttl_seconds)
    payload = {
        "v": 1,
        "iat": int(issued.timestamp()),
        "exp": int(expires.timestamp()),
    }
    payload_bytes = _canonical_payload(payload)
    return f"{_b64encode(payload_bytes)}.{_signature(config.cookie_secret, payload_bytes)}"


def verify_remember_token(
    config: DashboardAuthConfig,
    token: str | None,
    *,
    now: datetime | None = None,
) -> bool:
    config.validate()
    if not token or not config.cookie_secret:
        return False
    try:
        encoded_payload, encoded_signature = token.split(".", maxsplit=1)
        payload_bytes = _b64decode(encoded_payload)
        expected_signature = _signature(config.cookie_secret, payload_bytes)
        if not hmac.compare_digest(expected_signature, encoded_signature):
            return False
        payload = json.loads(payload_bytes.decode("utf-8"))
        if payload.get("v") != 1:
            return False
        expires_at = int(payload["exp"])
    except Exception:
        return False
    checked_at = now or _now()
    return expires_at >= int(checked_at.timestamp())


def pin_matches(config: DashboardAuthConfig, submitted_pin: str | None) -> bool:
    config.validate()
    if not config.pin or submitted_pin is None:
        return False
    if not (submitted_pin.isdigit() and len(submitted_pin) == 4):
        return False
    return hmac.compare_digest(config.pin, submitted_pin)


def evaluate_access(
    config: DashboardAuthConfig,
    *,
    submitted_pin: str | None = None,
    remember_token: str | None = None,
    now: datetime | None = None,
) -> DashboardAccessDecision:
    config.validate()
    if not config.enabled:
        return DashboardAccessDecision(authenticated=True, reason="auth_disabled")
    if verify_remember_token(config, remember_token, now=now):
        return DashboardAccessDecision(authenticated=True, reason="valid_cookie")
    if pin_matches(config, submitted_pin):
        return DashboardAccessDecision(
            authenticated=True,
            reason="pin_accepted",
            remember_token=create_remember_token(config, issued_at=now),
        )
    if submitted_pin:
        return DashboardAccessDecision(authenticated=False, reason="pin_rejected")
    if remember_token:
        return DashboardAccessDecision(authenticated=False, reason="cookie_rejected")
    return DashboardAccessDecision(authenticated=False, reason="login_required")


def remember_authenticated_browser(
    config: DashboardAuthConfig,
    controller: CookieController,
    token: str,
) -> None:
    config.validate()
    controller.set(
        config.cookie_name,
        token,
        max_age=config.cookie_ttl_seconds,
    )


def forget_authenticated_browser(
    config: DashboardAuthConfig,
    controller: CookieController,
) -> None:
    config.validate()
    controller.remove(config.cookie_name)
