"""Supabase Auth calls. No passwords or refresh tokens are stored by this app."""

from uuid import UUID

import httpx


class AuthError(Exception):
    def __init__(self, message, status=401):
        super().__init__(message)
        self.status = status


class SupabaseAuth:
    def __init__(self, url, key):
        self.url = url.rstrip("/")
        self.key = key

    def _request(self, method, path, token=None, body=None):
        if not self.url or not self.key:
            raise AuthError("Sign-in is not configured yet.", 503)
        headers = {"apikey": self.key}
        # The API key identifies the project; the access token identifies the user.
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            response = httpx.request(
                method, self.url + "/auth/v1/" + path,
                headers=headers, json=body, timeout=12,
            )
        except httpx.HTTPError as exc:
            raise AuthError("The sign-in service is temporarily unavailable.", 503) from exc
        if response.status_code == 429:
            raise AuthError("Too many attempts. Please wait before trying again.", 429)
        if response.status_code >= 500:
            raise AuthError("The sign-in service is temporarily unavailable.", 503)
        if response.status_code >= 400:
            raise AuthError("Sign-in failed. Check your details and email confirmation.")
        return response.json() if response.content else {}

    def login(self, email, password):
        return self._request("POST", "token?grant_type=password", body={
            "email": email, "password": password,
        })

    def signup(self, email, password):
        return self._request("POST", "signup", body={"email": email, "password": password})

    def user(self, token):
        # Ask Supabase to validate the token and return the account identity.
        data = self._request("GET", "user", token=token)
        try:
            user_id = str(UUID(data["id"]))
        except (KeyError, ValueError, TypeError) as exc:
            raise AuthError("Your session is invalid. Please sign in again.") from exc
        return {"id": user_id, "email": data.get("email", "Signed-in user")}

    def logout(self, token):
        self._request("POST", "logout?scope=local", token=token)
