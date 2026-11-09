"""Central configuration shared by the tools, the graph, the ingestion layer and the UI.

Values are read from the environment (see `.env.example`) with safe defaults so
the system can still be imported and unit-tested without a populated `.env`.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load `.env` from the project root if present (no-op when missing).
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def _get_str(name: str, default: str) -> str:
    value = os.getenv(name)
    return default if value is None or not str(value).strip() else str(value).strip()


def _get_optional(name: str) -> str | None:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else None


def _get_int(name: str, default: int, *, lo: int | None = None, hi: int | None = None) -> int:
    """Read an int from the environment, clamped to [lo, hi]; fall back on bad input."""
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        value = int(float(str(raw).strip()))
    except (TypeError, ValueError):
        return default
    if lo is not None:
        value = max(lo, value)
    if hi is not None:
        value = min(hi, value)
    return value


def _get_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None or not str(value).strip():
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


# --------------------------------------------------------------------------- #
# Knowledge base / LLM
# --------------------------------------------------------------------------- #
CHROMA_PATH: str = _get_str("CHROMA_PATH", str(PROJECT_ROOT / "chroma_db"))
COLLECTION_NAME: str = "hr_requisitions"

OPENAI_MODEL: str = _get_str("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_BASE_URL: str | None = _get_optional("OPENAI_BASE_URL")

# Candidates scoring at or above this threshold are invited; below, rejected.
FIT_THRESHOLD: int = _get_int("FIT_THRESHOLD", 70, lo=0, hi=100)

GITHUB_TOKEN: str | None = _get_optional("GITHUB_TOKEN")

OPENAI_API_KEY: str | None = _get_optional("OPENAI_API_KEY")

FALLBACK_MODEL: str = _get_str("FALLBACK_MODEL", "")
FALLBACK_BASE_URL: str | None = _get_optional("FALLBACK_BASE_URL")
FALLBACK_API_KEY: str | None = _get_optional("FALLBACK_API_KEY")

# --------------------------------------------------------------------------- #
# Email ingestion (Gmail MCP)
# --------------------------------------------------------------------------- #
# "local" reads *.eml fixtures from disk (offline/demo); "mcp" talks to a Gmail MCP.
EMAIL_SOURCE: str = _get_str("EMAIL_SOURCE", "local").lower()

# Option A: spawn an MCP server over stdio, e.g.
#   GMAIL_MCP_COMMAND="npx -y @gongrzhe/server-gmail-autoauth-mcp"
GMAIL_MCP_COMMAND: str | None = _get_optional("GMAIL_MCP_COMMAND")
# Option B: connect to an already-running MCP server over SSE/HTTP.
GMAIL_MCP_URL: str | None = _get_optional("GMAIL_MCP_URL")
# Name of the MCP tool used to search/list messages (contract documented in
# src/ingest/gmail_mcp_source.py).
GMAIL_MCP_SEARCH_TOOL: str = _get_str("GMAIL_MCP_SEARCH_TOOL", "search_emails")
GMAIL_MCP_TIMEOUT: int = _get_int("GMAIL_MCP_TIMEOUT", 30, lo=1, hi=600)

# Where LocalFileSource looks for .eml fixtures when EMAIL_SOURCE=local.
LOCAL_MAILBOX_PATH: str = _get_str(
    "LOCAL_MAILBOX_PATH", str(PROJECT_ROOT / "tests" / "fixtures" / "mail")
)

# Default Gmail filters (label + query are combined at fetch time).
GMAIL_LABEL: str = _get_str("GMAIL_LABEL", "")
GMAIL_QUERY: str = _get_str("GMAIL_QUERY", "has:attachment")
GMAIL_MAX_RESULTS: int = _get_int("GMAIL_MAX_RESULTS", 25, lo=1, hi=500)
GMAIL_LOOKBACK_DAYS: int = _get_int("GMAIL_LOOKBACK_DAYS", 30, lo=1, hi=3650)

# --------------------------------------------------------------------------- #
# Applicant roster
# --------------------------------------------------------------------------- #
ROSTER_DB_PATH: str = _get_str(
    "ROSTER_DB_PATH", str(PROJECT_ROOT / "data" / "applicants.db")
)
# When true, ingestion also runs the full LLM screening for every new applicant.
# Default is False: ingest is light, screening is triggered on demand (HITL/cost).
SCREEN_ON_IMPORT: bool = _get_bool("SCREEN_ON_IMPORT", default=False)
# Optional comma-separated override of the default specialization taxonomy.
# TAXONOMY is accepted as a legacy alias.
TAXONOMY_OVERRIDE: str = _get_str("TAXONOMY_OVERRIDE", _get_str("TAXONOMY", ""))

# --------------------------------------------------------------------------- #
# Safety limits
# --------------------------------------------------------------------------- #
# Hard cap on resume text handed to the LLM / stored, to bound tokens and cost.
MAX_RESUME_CHARS: int = _get_int("MAX_RESUME_CHARS", 20000, lo=1000, hi=200000)
# Hard cap on pages read from a PDF, to bound pathological files.
MAX_PDF_PAGES: int = _get_int("MAX_PDF_PAGES", 50, lo=1, hi=1000)
# GitHub result TTL cache (seconds). 0 disables caching.
GITHUB_CACHE_TTL: int = _get_int("GITHUB_CACHE_TTL", 0, lo=0, hi=86400)
