from __future__ import annotations

import base64
import secrets
import time
from threading import RLock
from urllib.parse import urlencode

import requests
from fastapi import Request

from services.config import config


AUTHORIZE_ENDPOINT = "https://connect.linux.do/oauth2/authorize"
TOKEN_ENDPOINT = "https://connect.linux.do/oauth2/token"
USER_ENDPOINT = "https://connect.linux.do/api/user"
_STATE_TTL_SECONDS = 10 * 60
_states: dict[str, float] = {}
_lock = RLock()


def _proxy_kwargs() -> dict[str, object]:
    proxy = config.get_proxy_settings()
    if not proxy:
        return {}
    return {"proxies": {"http": proxy, "https": proxy}}


def request_base_url(request: Request) -> str:
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}".rstrip("/")


def callback_url(request: Request) -> str:
    return f"{request_base_url(request)}/oauth/linuxdo"


def frontend_callback_url(request: Request) -> str:
    return f"{request_base_url(request)}/oauth/callback"


def _create_state() -> str:
    state = secrets.token_urlsafe(24)
    now = time.time()
    with _lock:
        expired = [key for key, expires_at in _states.items() if expires_at < now]
        for key in expired:
            _states.pop(key, None)
        _states[state] = now + _STATE_TTL_SECONDS
    return state


def _consume_state(state: str) -> None:
    if not state:
        raise ValueError("oauth state is missing")
    now = time.time()
    with _lock:
        expires_at = _states.pop(state, None)
    if expires_at is None or expires_at < now:
        raise ValueError("oauth state is invalid or expired")


def authorization_url(request: Request) -> str:
    if not config.linuxdo_oauth_enabled:
        raise ValueError("Linux DO OAuth is disabled")
    if not config.linuxdo_client_id or not config.linuxdo_client_secret:
        raise ValueError("Linux DO OAuth is not configured")
    query = urlencode(
        {
            "client_id": config.linuxdo_client_id,
            "redirect_uri": callback_url(request),
            "response_type": "code",
            "scope": "read",
            "state": _create_state(),
        }
    )
    return f"{AUTHORIZE_ENDPOINT}?{query}"


def _exchange_token(code: str, redirect_uri: str) -> str:
    if not code:
        raise ValueError("oauth code is missing")
    credentials = f"{config.linuxdo_client_id}:{config.linuxdo_client_secret}"
    basic_auth = base64.b64encode(credentials.encode("utf-8")).decode("ascii")
    response = requests.post(
        TOKEN_ENDPOINT,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        },
        headers={
            "Authorization": f"Basic {basic_auth}",
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        timeout=10,
        **_proxy_kwargs(),
    )
    if response.status_code >= 400:
        raise ValueError(f"Linux DO token exchange failed: HTTP {response.status_code}")
    data = response.json()
    token = str(data.get("access_token") or "").strip()
    if not token:
        raise ValueError(str(data.get("message") or "Linux DO token exchange failed"))
    return token


def _fetch_user(access_token: str) -> dict[str, object]:
    response = requests.get(
        USER_ENDPOINT,
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        timeout=10,
        **_proxy_kwargs(),
    )
    if response.status_code >= 400:
        raise ValueError(f"Linux DO user fetch failed: HTTP {response.status_code}")
    data = response.json()
    if not isinstance(data, dict) or not data.get("id"):
        raise ValueError("Linux DO user info is empty")
    return data


def authenticate_callback(request: Request, code: str, state: str) -> dict[str, object]:
    _consume_state(state)
    access_token = _exchange_token(code, callback_url(request))
    user = _fetch_user(access_token)
    trust_level = int(user.get("trust_level") or 0)
    if not bool(user.get("active", True)):
        raise ValueError("Linux DO account is not active")
    if bool(user.get("silenced", False)):
        raise ValueError("Linux DO account is silenced")
    if trust_level < config.linuxdo_minimum_trust_level:
        raise ValueError(
            f"Linux DO trust level too low: required {config.linuxdo_minimum_trust_level}, current {trust_level}"
        )
    return {
        "provider_user_id": str(user.get("id") or ""),
        "username": str(user.get("username") or "").strip(),
        "display_name": str(user.get("name") or user.get("username") or "").strip(),
        "trust_level": trust_level,
        "active": bool(user.get("active", True)),
        "silenced": bool(user.get("silenced", False)),
    }
