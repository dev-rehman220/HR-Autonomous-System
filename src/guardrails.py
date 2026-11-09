"""Guardrails implementing `docs/08_guardrails_rules.md`.

These helpers are applied *before* candidate text is handed to any external
system (LLM provider, GitHub API) so that personally identifiable information is
not leaked, and protected attributes cannot influence scoring.
"""
from __future__ import annotations

import re

# --- PII patterns -----------------------------------------------------------

# US Social Security Number.
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")

# Common phone shapes: +1 555-123-4567, (555) 123-4567, 555.123.4567, 5551234567.
_PHONE_RE = re.compile(
    r"(?:(?:\+?\d{1,3})[\s.\-]?)?"          # optional country code
    r"(?:\(\d{2,4}\)[\s.\-]?|\d{2,4}[\s.\-])"  # area code
    r"\d{3,4}[\s.\-]?\d{3,4}"                # local number
)

# Street addresses ending in a recognised suffix.
_ADDRESS_RE = re.compile(
    r"\b\d{1,5}\s+[A-Za-z0-9.\-]+(?:\s+[A-Za-z0-9.\-]+){0,4}\s+"
    r"(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|"
    r"Court|Ct|Way|Place|Pl|Terrace|Ter|Circle|Cir)\b\.?",
    re.IGNORECASE,
)

# --- Bias-signal patterns ---------------------------------------------------

_BIAS_RES = [
    re.compile(r"\b(?:age|aged)\s*[:\-]?\s*\d{1,3}\b", re.IGNORECASE),
    re.compile(r"\bdate\s+of\s+birth\b\s*[:\-]?.*", re.IGNORECASE),
    re.compile(r"\b(?:d\.?o\.?b\.?)\b\s*[:\-]?.*", re.IGNORECASE),
    re.compile(r"\b(?:graduated|graduation)\b[^\n]*\b(?:19|20)\d{2}\b", re.IGNORECASE),
    re.compile(r"\b(?:gender|sex|marital\s+status|nationality|religion)\b\s*[:\-]?[^\n]*", re.IGNORECASE),
]


def scrub_pii(text: str) -> str:
    """Replace phone numbers, home addresses, and SSNs with redaction tokens."""
    if not text:
        return ""
    scrubbed = _SSN_RE.sub("[REDACTED-SSN]", text)
    scrubbed = _ADDRESS_RE.sub("[REDACTED-ADDRESS]", scrubbed)
    scrubbed = _PHONE_RE.sub("[REDACTED-PHONE]", scrubbed)
    return scrubbed


def strip_bias_signals(text: str) -> str:
    """Remove protected-attribute signals (age, DOB, graduation year, gender...).

    Scoring prompts receive the stripped text so that these attributes cannot be
    used, deliberately or accidentally, in candidate evaluation.
    """
    if not text:
        return ""
    stripped = text
    for pattern in _BIAS_RES:
        stripped = pattern.sub("[REDACTED-BIAS]", stripped)
    return stripped


def prepare_for_external(text: str) -> str:
    """Full scrub applied before sending candidate text to any external system."""
    return strip_bias_signals(scrub_pii(text))


# --- Salary-leak patterns ---------------------------------------------------
# Candidate-facing drafts must never leak internal compensation (docs/08 #4):
# covers "$140,000", "$140k", "140,000 USD", "£140,000", "140k per year".
_SALARY_RES = [
    re.compile(r"[$£€]\s?\d[\d,]*(?:\.\d+)?\s?[kK]\b"),
    re.compile(r"[$£€]\s?\d{1,3}(?:,\d{3})+(?:\.\d+)?"),
    re.compile(r"[$£€]\s?\d{4,}(?:\.\d+)?"),
    re.compile(
        r"\b\d{1,3}(?:,\d{3})+\s?(?:usd|eur|gbp|dollars?|pounds?|euros?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b\d[\d,\.]*\s?[kK]\s?(?:per\s+(?:year|annum|month|hour)|/yr|/year|/mo|/hour)\b",
        re.IGNORECASE,
    ),
]


def find_salary_leaks(text: str) -> list[str]:
    """Return every salary-like substring found in `text` (empty when clean)."""
    if not text:
        return []
    leaks: list[str] = []
    for pattern in _SALARY_RES:
        leaks.extend(match.group(0).strip() for match in pattern.finditer(text))
    return leaks


def assert_no_salary(text: str) -> bool:
    """Guard for candidate-facing drafts: return True when no salary figure leaks."""
    return not find_salary_leaks(text or "")
