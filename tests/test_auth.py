import httpx
import pytest

from auth import AuthError, SupabaseAuth


def test_user_identity_is_obtained_from_supabase_not_unverified_claims(monkeypatch):
    calls = []
    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return httpx.Response(200, json={"id": "11111111-1111-4111-8111-111111111111", "email": "student@example.com"})
    monkeypatch.setattr(httpx, "request", request)
    service = SupabaseAuth("https://example.supabase.co", "publishable-test-value")
    assert service.user("session-token")["email"] == "student@example.com"
    assert calls[0][0:2] == ("GET", "https://example.supabase.co/auth/v1/user")
    assert calls[0][2]["headers"]["Authorization"] == "Bearer session-token"


@pytest.mark.parametrize("status, expected", [(401, 401), (429, 429), (503, 503)])
def test_provider_errors_are_sanitized(monkeypatch, status, expected):
    monkeypatch.setattr(httpx, "request", lambda *a, **k: httpx.Response(status, json={"detail": "internal-secret"}))
    with pytest.raises(AuthError) as error:
        SupabaseAuth("https://example.supabase.co", "publishable-test-value").user("bad-token")
    assert error.value.status == expected
    assert "internal-secret" not in str(error.value)
