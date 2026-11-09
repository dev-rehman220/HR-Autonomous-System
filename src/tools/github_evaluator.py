"""GitHub Profile Evaluator Tool (FR-3).

Queries the public GitHub REST API to verify a candidate's claimed engineering
activity. Degrades gracefully (never raises) when the handle is missing, the
account is unreachable, or the API is rate-limited (NFR: Reliability).
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

from src.config import GITHUB_CACHE_TTL, GITHUB_TOKEN

logger = logging.getLogger(__name__)

API_BASE = "https://api.github.com"
RECENT_ACTIVITY_WINDOW_DAYS = 180
REQUEST_TIMEOUT = 8
MAX_BACKOFF_ATTEMPTS = 3

_cache: dict[str, tuple[float, dict]] = {}


def _headers() -> dict:
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return headers


def _unverified(reason: str) -> dict:
    """Normalised 'could not verify' payload (keeps the output schema stable)."""
    return {
        "user_exists": False,
        "public_repos": 0,
        "primary_languages": [],
        "pinned_projects": [],
        "recent_commit_activity": False,
        "verified": False,
        "reason": reason,
    }


def _is_recent(pushed_at: Optional[str]) -> bool:
    if not pushed_at:
        return False
    try:
        pushed_dt = datetime.fromisoformat(pushed_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    return (datetime.now(timezone.utc) - pushed_dt) < timedelta(days=RECENT_ACTIVITY_WINDOW_DAYS)


def clear_cache() -> None:
    """Drop memoised GitHub responses (used between runs/tests)."""
    _cache.clear()


def _cache_get(username: str) -> Optional[dict]:
    if GITHUB_CACHE_TTL <= 0:
        return None
    entry = _cache.get(username)
    if entry is None:
        return None
    expires_at, value = entry
    if time.monotonic() >= expires_at:
        _cache.pop(username, None)
        return None
    return value


def _cache_set(username: str, value: dict) -> None:
    if GITHUB_CACHE_TTL > 0:
        _cache[username] = (time.monotonic() + GITHUB_CACHE_TTL, value)


def _retry_after_seconds(response: requests.Response, default: float) -> float:
    headers = getattr(response, "headers", None)
    raw = headers.get("Retry-After") if hasattr(headers, "get") else None
    try:
        return max(1.0, float(raw))
    except (TypeError, ValueError):
        return default


def _get(url: str, params: Optional[dict] = None) -> Optional[requests.Response]:
    """GET with bounded exponential backoff on 429/5xx and network errors."""
    delay = 1.0
    response: Optional[requests.Response] = None
    for attempt in range(MAX_BACKOFF_ATTEMPTS):
        try:
            response = requests.get(
                url, headers=_headers(), params=params, timeout=REQUEST_TIMEOUT
            )
        except requests.RequestException as exc:
            logger.warning("GitHub request to %s failed: %s", url, exc)
            response = None
        if response is not None:
            throttled = response.status_code == 429 or response.status_code >= 500
            if throttled and attempt < MAX_BACKOFF_ATTEMPTS - 1:
                time.sleep(_retry_after_seconds(response, delay))
                delay *= 2
                continue
            return response
        if attempt < MAX_BACKOFF_ATTEMPTS - 1:
            time.sleep(delay)
            delay *= 2
    return response


def _rate_limited(response: requests.Response) -> bool:
    headers = getattr(response, "headers", None)
    remaining = headers.get("X-RateLimit-Remaining") if hasattr(headers, "get") else None
    # No header info: treat 403 conservatively as rate limiting (the common cause).
    return remaining is None or str(remaining) == "0"


def evaluate_github_profile(username: Optional[str]) -> dict:
    """Return repository/language/activity signals for a GitHub username."""
    if not username:
        return _unverified("No GitHub handle provided")

    cache_key = username.strip().lower()
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    user_resp = _get(f"{API_BASE}/users/{username}")
    if user_resp is None:
        return _unverified("GitHub request failed after retries")

    status = user_resp.status_code
    if status == 404:
        return _unverified("GitHub user not found")
    if status == 429:
        return _unverified("GitHub API rate limit exceeded")
    if status == 403:
        if _rate_limited(user_resp):
            return _unverified("GitHub API rate limit exceeded")
        return _unverified("GitHub access forbidden (403)")
    if status != 200:
        return _unverified(f"GitHub API error ({status})")

    user = user_resp.json()

    repos: list[dict] = []
    repos_resp = _get(
        f"{API_BASE}/users/{username}/repos",
        params={"per_page": 30, "sort": "pushed", "direction": "desc"},
    )
    if repos_resp is not None and repos_resp.status_code == 200:
        parsed = repos_resp.json()
        if isinstance(parsed, list):
            repos = [repo for repo in parsed if isinstance(repo, dict)]

    owned = [repo for repo in repos if not repo.get("fork") and not repo.get("archived")]
    if not owned:
        owned = repos

    languages = sorted({repo["language"] for repo in owned if repo.get("language")})
    top_repos = sorted(owned, key=lambda r: r.get("stargazers_count", 0), reverse=True)[:3]
    pinned_projects = [
        {"name": repo.get("name", "unknown"), "stars": repo.get("stargazers_count", 0)}
        for repo in top_repos
    ]

    result = {
        "user_exists": True,
        "username": username,
        "public_repos": user.get("public_repos", 0),
        "primary_languages": languages,
        "pinned_projects": pinned_projects,
        "recent_commit_activity": any(_is_recent(repo.get("pushed_at")) for repo in owned),
        "verified": True,
        "reason": None,
    }
    _cache_set(cache_key, result)
    return result
