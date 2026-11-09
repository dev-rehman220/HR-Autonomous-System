"""Unit tests for the standalone tools (Phase 3, plus TC-04).

No network access or OpenAI key is required: the GitHub calls are monkeypatched
and resume parsing is exercised with both real text and a hand-built PDF.
"""
from __future__ import annotations

import pytest

from src.guardrails import assert_no_salary, prepare_for_external, scrub_pii
from src.tools import github_evaluator
from src.tools.github_evaluator import evaluate_github_profile
from src.tools.resume_parser import ResumeParseError, parse_resume, parse_resume_text
from src.tools.scheduler import (
    draft_interview_email,
    draft_rejection_email,
    fetch_recruiter_schedule,
)

SAMPLE_RESUME = """\
JANE DOE
jane.doe@example.com | +1 (555) 123-4567
github.com/janedoe
123 Main Street, Springfield

SUMMARY
Backend engineer with 6 years of experience building Python services.

SKILLS
Python, FastAPI, Docker, PostgreSQL, AWS, LangChain, React

EXPERIENCE
Senior Engineer - built distributed services.
"""


def _build_pdf(lines: list[str]) -> bytes:
    """Build a tiny but valid single-page PDF containing `lines` of text."""

    def esc(value: str) -> str:
        return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    ops = ["BT", "/F1 12 Tf", "72 720 Td", "14 TL"]
    for line in lines:
        ops.append(f"({esc(line)}) Tj")
        ops.append("T*")
    ops.append("ET")
    stream = "\n".join(ops).encode("latin-1")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += str(index).encode() + b" 0 obj\n" + obj + b"\nendobj\n"

    xref_pos = len(out)
    out += b"xref\n0 " + str(len(objects) + 1).encode() + b"\n"
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += b"trailer\n<< /Size " + str(len(objects) + 1).encode() + b" /Root 1 0 R >>\n"
    out += b"startxref\n" + str(xref_pos).encode() + b"\n%%EOF"
    return bytes(out)


# --------------------------------------------------------------------------- #
# Resume parser
# --------------------------------------------------------------------------- #
def test_parse_resume_text_extracts_all_fields():
    parsed = parse_resume_text(SAMPLE_RESUME)
    assert parsed["full_name"] == "Jane Doe"
    assert parsed["email"] == "jane.doe@example.com"
    assert parsed["github_username"] == "janedoe"
    assert parsed["experience_years"] == 6.0
    for skill in ("Python", "FastAPI", "Docker", "PostgreSQL", "AWS"):
        assert skill in parsed["skills"]
    assert parsed["raw_text"] == SAMPLE_RESUME


def test_parse_resume_text_without_github_or_experience():
    parsed = parse_resume_text("John Smith\njohn@smith.dev\nPython developer.")
    assert parsed["github_username"] is None
    assert parsed["experience_years"] == 0.0
    assert parsed["email"] == "john@smith.dev"


def test_parse_resume_rejects_empty_bytes():
    with pytest.raises(ResumeParseError):
        parse_resume(b"")


def test_parse_resume_rejects_corrupt_pdf():
    # TC-04: a corrupt/unreadable PDF must fail gracefully, not crash.
    with pytest.raises(ResumeParseError):
        parse_resume(b"this is definitely not a pdf")


def test_parse_resume_reads_a_real_pdf():
    pdf = _build_pdf(
        ["Jane Doe", "jane@example.com", "github.com/janedoe", "Python, Docker", "5 years"]
    )
    parsed = parse_resume(pdf)
    assert parsed["email"] == "jane@example.com"
    assert parsed["github_username"] == "janedoe"
    assert parsed["experience_years"] == 5.0


# --------------------------------------------------------------------------- #
# GitHub evaluator
# --------------------------------------------------------------------------- #
class _FakeResponse:
    def __init__(self, status_code: int = 200, payload: object | None = None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


def test_evaluate_github_profile_without_handle():
    result = evaluate_github_profile(None)
    assert result["user_exists"] is False
    assert result["verified"] is False
    assert result["reason"]


def test_evaluate_github_profile_verifies_real_account(monkeypatch):
    user = {"public_repos": 12}
    repos = [
        {"name": "agent", "language": "Python", "stargazers_count": 40,
         "pushed_at": "2999-01-01T00:00:00Z"},
        {"name": "api", "language": "Go", "stargazers_count": 5,
         "pushed_at": "2020-01-01T00:00:00Z"},
    ]

    def fake_get(url, headers=None, params=None, timeout=None):
        if url.endswith("/repos"):
            return _FakeResponse(200, repos)
        return _FakeResponse(200, user)

    monkeypatch.setattr(github_evaluator.requests, "get", fake_get)

    result = evaluate_github_profile("octocat")
    assert result["user_exists"] is True
    assert result["verified"] is True
    assert result["public_repos"] == 12
    assert set(result["primary_languages"]) == {"Python", "Go"}
    assert result["recent_commit_activity"] is True
    assert result["pinned_projects"][0] == {"name": "agent", "stars": 40}


def test_evaluate_github_profile_not_found(monkeypatch):
    monkeypatch.setattr(
        github_evaluator.requests, "get", lambda *a, **k: _FakeResponse(404)
    )
    result = evaluate_github_profile("ghost-user")
    assert result["user_exists"] is False
    assert "not found" in result["reason"].lower()


def test_evaluate_github_profile_rate_limited(monkeypatch):
    monkeypatch.setattr(
        github_evaluator.requests, "get", lambda *a, **k: _FakeResponse(403)
    )
    result = evaluate_github_profile("octocat")
    assert result["verified"] is False
    assert "rate limit" in result["reason"].lower()


# --------------------------------------------------------------------------- #
# Scheduler & dispatch
# --------------------------------------------------------------------------- #
def test_fetch_recruiter_schedule_returns_three_weekday_slots():
    slots = fetch_recruiter_schedule("rec_42")
    assert len(slots) == 3
    for slot in slots:
        assert slot["slot_id"].startswith("rec_42")
        assert slot["datetime_iso"]
        assert slot["display"]


def test_draft_interview_email_includes_details_and_no_salary():
    slots = fetch_recruiter_schedule()
    email = draft_interview_email("Jane Doe", "AI Engineer", slots)
    assert "Jane Doe" in email
    assert "AI Engineer" in email
    assert slots[0]["display"] in email
    assert "Interview Invitation" in email
    assert assert_no_salary(email)  # guardrail #4: no internal salary leaks


def test_draft_rejection_email_is_respectful_and_slotless():
    email = draft_rejection_email("Jane Doe", "AI Engineer")
    assert "Jane Doe" in email
    assert "AI Engineer" in email
    assert "thank you" in email.lower()
    assert assert_no_salary(email)


# --------------------------------------------------------------------------- #
# Guardrails
# --------------------------------------------------------------------------- #
def test_scrub_pii_redacts_phone_ssn_and_address():
    scrubbed = scrub_pii("Call +1 (555) 123-4567, SSN 123-45-6789, 123 Main Street.")
    assert "123-45-6789" not in scrubbed
    assert "555) 123-4567" not in scrubbed
    assert "123 Main Street" not in scrubbed


def test_prepare_for_external_removes_bias_signals_keeps_skills():
    prepared = prepare_for_external("Age: 41. Graduated in 2005. Python expert.")
    assert "41" not in prepared
    assert "2005" not in prepared
    assert "Python expert" in prepared
