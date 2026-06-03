from datetime import UTC, datetime, timedelta

from alphadb.dashboard.auth import (
    DashboardAuthConfig,
    create_remember_token,
    evaluate_access,
    forget_authenticated_browser,
    remember_authenticated_browser,
    verify_remember_token,
)


class FakeCookieController:
    def __init__(self) -> None:
        self.cookies: dict[str, str] = {}
        self.max_age: dict[str, int] = {}
        self.removed: list[str] = []

    def get(self, name: str) -> str | None:
        return self.cookies.get(name)

    def set(self, name: str, value: str, *, max_age: int) -> None:
        self.cookies[name] = value
        self.max_age[name] = max_age

    def remove(self, name: str) -> None:
        self.removed.append(name)
        self.cookies.pop(name, None)


def auth_config() -> DashboardAuthConfig:
    return DashboardAuthConfig(
        pin="1234",
        cookie_secret="test-cookie-secret",
        cookie_ttl_seconds=3600,
        cookie_name="alphadb_test_auth",
    )


def test_dashboard_access_is_open_when_auth_is_not_configured() -> None:
    decision = evaluate_access(
        DashboardAuthConfig(
            pin=None,
            cookie_secret=None,
            cookie_ttl_seconds=3600,
            cookie_name="alphadb_test_auth",
        )
    )

    assert decision.authenticated is True
    assert decision.reason == "auth_disabled"


def test_dashboard_access_accepts_pin_and_issues_signed_remember_token() -> None:
    now = datetime(2026, 6, 1, 12, tzinfo=UTC)

    decision = evaluate_access(auth_config(), submitted_pin="1234", now=now)

    assert decision.authenticated is True
    assert decision.reason == "pin_accepted"
    assert decision.remember_token is not None
    assert "1234" not in decision.remember_token
    assert verify_remember_token(auth_config(), decision.remember_token, now=now)


def test_dashboard_access_rejects_bad_or_malformed_pin() -> None:
    assert evaluate_access(auth_config(), submitted_pin="9999").authenticated is False
    assert evaluate_access(auth_config(), submitted_pin="abcd").authenticated is False
    assert evaluate_access(auth_config(), submitted_pin="12345").authenticated is False


def test_dashboard_access_accepts_valid_cookie() -> None:
    now = datetime(2026, 6, 1, 12, tzinfo=UTC)
    token = create_remember_token(auth_config(), issued_at=now)

    decision = evaluate_access(auth_config(), remember_token=token, now=now + timedelta(minutes=30))

    assert decision.authenticated is True
    assert decision.reason == "valid_cookie"


def test_dashboard_access_rejects_expired_or_tampered_cookie() -> None:
    now = datetime(2026, 6, 1, 12, tzinfo=UTC)
    token = create_remember_token(auth_config(), issued_at=now)
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")

    assert verify_remember_token(auth_config(), token, now=now + timedelta(hours=2)) is False
    assert verify_remember_token(auth_config(), tampered, now=now) is False
    assert evaluate_access(auth_config(), remember_token=tampered, now=now).authenticated is False


def test_cookie_controller_helpers_set_and_remove_signed_token() -> None:
    controller = FakeCookieController()
    token = create_remember_token(auth_config(), issued_at=datetime(2026, 6, 1, 12, tzinfo=UTC))

    remember_authenticated_browser(auth_config(), controller, token)
    forget_authenticated_browser(auth_config(), controller)

    assert controller.max_age["alphadb_test_auth"] == 3600
    assert controller.cookies == {}
    assert controller.removed == ["alphadb_test_auth"]
