"""API key authentication and Redis-backed rate limiting for the orchestrator API."""

from __future__ import annotations

import time

from django.conf import settings
from rest_framework import authentication, exceptions, permissions, throttling


class APIKeyUser:
    """Lightweight authenticated principal representing a valid API key."""

    is_authenticated = True

    def __init__(self, key_id: str = "api-key"):
        self.key_id = key_id

    def __str__(self) -> str:
        return self.key_id


def _extract_api_key(request) -> str | None:
    header = request.META.get("HTTP_X_API_KEY") or request.headers.get("X-API-Key")
    if header:
        return header.strip()

    auth = request.META.get("HTTP_AUTHORIZATION", "")
    if auth.lower().startswith("api-key "):
        return auth[8:].strip()
    return None


class APIKeyAuthentication(authentication.BaseAuthentication):
    """
    Authenticate via:
      - Header: X-API-Key: <key>
      - Header: Authorization: Api-Key <key>
    """

    def authenticate(self, request):
        provided = _extract_api_key(request)
        expected = getattr(settings, "API_KEY", "") or ""
        if not expected:
            raise exceptions.AuthenticationFailed("API_KEY is not configured on the server")
        # Missing or invalid key → 401 (not 403) so clients can distinguish auth failures
        if not provided:
            raise exceptions.AuthenticationFailed("API key required")
        if provided != expected:
            raise exceptions.AuthenticationFailed("Invalid API key")
        return (APIKeyUser(), provided)

    def authenticate_header(self, request):
        # Required so DRF returns 401 instead of coercing AuthenticationFailed → 403
        return "Api-Key"


class IsAPIKeyAuthenticated(permissions.BasePermission):
    """Require a successfully authenticated API key principal."""

    def has_permission(self, request, view):
        return bool(request.user and getattr(request.user, "is_authenticated", False))


class APIKeyRateThrottle(throttling.BaseThrottle):
    """
    Simple fixed-window rate limit per API key (or IP if anonymous).
    Uses Redis INCR + EXPIRE when available; falls back to allowing the request.
    """

    def allow_request(self, request, view):
        limit = int(getattr(settings, "RATE_LIMIT_PER_MINUTE", 30))
        if limit <= 0:
            return True

        key_id = _extract_api_key(request) or request.META.get("REMOTE_ADDR", "anon")
        bucket = int(time.time() // 60)
        redis_key = f"ratelimit:{key_id}:{bucket}"

        try:
            from core.redis_client import get_redis

            client = get_redis()
            count = client.incr(redis_key)
            if count == 1:
                client.expire(redis_key, 70)
            if count > limit:
                self.wait_seconds = 60 - int(time.time() % 60)
                return False
            return True
        except Exception:
            # Fail open if Redis is unavailable so health of infra isn't blocked by throttle
            return True

    def wait(self):
        return getattr(self, "wait_seconds", 60)
