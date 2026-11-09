"""Resume Parser Tool (FR-1).

Extracts structured candidate data from an uploaded PDF resume. Text parsing is
split from PDF I/O (`parse_resume_text` vs `parse_resume`) so the extraction
logic can be unit tested without a binary fixture.
"""
from __future__ import annotations

import re
from io import BytesIO
from typing import Optional

from pypdf import PdfReader

from src.config import MAX_PDF_PAGES, MAX_RESUME_CHARS

# Baseline technical stack used to detect declared skills on the resume.
COMMON_SKILLS: list[str] = [
    "Python", "FastAPI", "Django", "Flask", "Docker", "Kubernetes",
    "PostgreSQL", "MySQL", "SQLite", "MongoDB", "Redis", "Kafka",
    "LangChain", "LangGraph", "PyTorch", "TensorFlow", "scikit-learn",
    "RAG", "LLM", "React", "TypeScript", "JavaScript", "Node.js",
    "AWS", "GCP", "Azure", "Git", "CI/CD", "Go", "Rust", "Java",
    "Airflow", "Spark", "GraphQL", "REST",
]

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
GITHUB_RE = re.compile(r"github\.com/([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))", re.IGNORECASE)
EXPERIENCE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)", re.IGNORECASE)

_CONTACT_RE = re.compile(
    r"(@|http|www\.|\+?\d[\d\s\-()]{6,}|resume|curriculum|objective|"
    r"summary|skills|experience|education|profile|contact|references|projects)",
    re.IGNORECASE,
)
_NAME_LINE_RE = re.compile(r"^[A-Za-z][A-Za-z.'\-]*(?:\s+[A-Za-z][A-Za-z.'\-]*){0,5}$")
_SECTION_WORDS = {
    "SUMMARY", "SKILLS", "EXPERIENCE", "EDUCATION", "PROFILE",
    "CONTACT", "OBJECTIVE", "REFERENCES", "PROJECTS", "RESUME", "CV",
}

NAME_SCAN_LINES = 15


class ResumeParseError(ValueError):
    """Raised when a PDF cannot be turned into usable resume text (e.g. TC-04)."""


def parse_resume_text(raw_text: str) -> dict:
    """Extract structured fields from resume text that has already been read."""
    text = raw_text or ""
    email_match = EMAIL_RE.search(text)
    email = email_match.group(0) if email_match else "unknown@domain.com"

    github_match = GITHUB_RE.search(text)
    github_username: Optional[str] = github_match.group(1) if github_match else None

    skills = [
        skill
        for skill in COMMON_SKILLS
        if re.search(rf"\b{re.escape(skill)}\b", text, re.IGNORECASE)
    ]

    return {
        "full_name": _extract_name(text),
        "email": email,
        "github_username": github_username,
        "skills": skills,
        "experience_years": _extract_experience(text),
        "raw_text": text[:MAX_RESUME_CHARS],
    }


def _extract_name(raw_text: str) -> str:
    """Heuristically pick the candidate name from the top of the resume."""
    for line in raw_text.splitlines()[:NAME_SCAN_LINES]:
        candidate = line.strip()
        if not candidate or len(candidate.split()) > 5 or _CONTACT_RE.search(candidate):
            continue
        if candidate.upper().strip(":").strip() in _SECTION_WORDS:
            continue
        if _NAME_LINE_RE.match(candidate):
            return candidate.title() if candidate.isupper() else candidate

    email_match = EMAIL_RE.search(raw_text)
    if email_match:
        local = re.sub(r"[._\-]+", " ", email_match.group(0).split("@")[0]).strip()
        if local and not local.isdigit():
            return local.title()

    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    return lines[0] if lines else "Candidate"


def _extract_experience(raw_text: str) -> float:
    """Return the largest 'N years' figure mentioned on the resume (0.0 if none)."""
    matches = [float(m.group(1)) for m in EXPERIENCE_RE.finditer(raw_text)]
    return max(matches) if matches else 0.0


def parse_resume(file_bytes: bytes) -> dict:
    """Parse a PDF resume given its raw bytes.

    Raises:
        ResumeParseError: for empty, encrypted, corrupt, or image-only PDFs so
            the workflow can halt safely (TC-04).
    """
    if not file_bytes:
        raise ResumeParseError("Empty file: no resume data received.")

    try:
        reader = PdfReader(BytesIO(file_bytes))
        if reader.is_encrypted:
            # Try the common empty-password case before giving up.
            if reader.decrypt("") == 0:
                raise ResumeParseError("Encrypted PDF: a password is required to read it.")
        pages = list(reader.pages)[:MAX_PDF_PAGES]
        raw_text = "\n".join((page.extract_text() or "") for page in pages)
    except ResumeParseError:
        raise
    except Exception as exc:  # noqa: BLE001 - pypdf raises a variety of errors
        raise ResumeParseError(f"Could not read PDF resume: {exc}") from exc

    if not raw_text.strip():
        raise ResumeParseError("No extractable text found (the PDF may be a scanned image).")

    return parse_resume_text(raw_text)
