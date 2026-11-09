"""End-to-end ingestion: fetch -> extract -> parse -> classify -> dedup -> upsert."""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field

from src.config import SCREEN_ON_IMPORT
from src.ingest.attachments import AttachmentExtractionError, extract_text, pick_cv_attachments
from src.ingest.email_source import (
    DEFAULT_LOOKBACK_DAYS,
    DEFAULT_MAX_RESULTS,
    EmailMessage,
    EmailSource,
)
from src.roster.classifier import classify
from src.roster.ranking import profile_strength_score
from src.roster.store import SqliteApplicantStore
from src.tools.resume_parser import parse_resume_text

logger = logging.getLogger(__name__)

_SENDER_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


@dataclass
class IngestResult:
    fetched: int = 0
    new: int = 0
    duplicates: int = 0
    skipped: int = 0
    screened: int = 0
    new_ids: list[int] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        text = (
            f"{self.fetched} email(s) fetched, {self.new} new applicant(s), "
            f"{self.duplicates} duplicate(s), {self.skipped} skipped, "
            f"{len(self.errors)} error(s)."
        )
        if self.screened:
            text += f" {self.screened} auto-screened."
        return text


def ingest(
    source: EmailSource,
    store: SqliteApplicantStore,
    *,
    label: str = "",
    query: str = "",
    max_results: int = DEFAULT_MAX_RESULTS,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> IngestResult:
    """Fetch emails from `source` and upsert any CVs found into the roster."""
    result = IngestResult()
    messages = source.fetch(
        label=label, query=query, max_results=max_results, lookback_days=lookback_days
    )
    result.fetched = len(messages)
    logger.info("Ingest fetched %d email(s)", result.fetched)
    for message in messages:
        _ingest_message(message, store, result)
    return result


def _ingest_message(
    message: EmailMessage, store: SqliteApplicantStore, result: IngestResult
) -> None:
    cv_attachments = pick_cv_attachments(message.attachments)
    if not cv_attachments:
        result.skipped += 1
        return

    attachment = cv_attachments[0]
    try:
        text = extract_text(attachment.filename, attachment.data, attachment.content_type)
    except AttachmentExtractionError as exc:
        result.errors.append(f"{message.message_id}: {exc}")
        result.skipped += 1
        return

    parsed = parse_resume_text(text)
    email = _resolve_email(parsed.get("email"), message.sender)
    specialization, confidence = classify(parsed, text=text)
    score = profile_strength_score(parsed.get("skills", []), parsed.get("experience_years", 0.0))

    status, applicant_id = store.upsert_candidate(
        full_name=parsed.get("full_name", "Candidate"),
        email=email,
        github_username=parsed.get("github_username"),
        specialization=specialization,
        skills=parsed.get("skills", []),
        experience_years=parsed.get("experience_years", 0.0),
        fit_score=score,
        confidence=confidence,
        cv_hash=hashlib.sha256(attachment.data).hexdigest(),
        message_id=message.message_id,
        source_subject=message.subject,
        source_date=message.date,
        resume_text=parsed.get("raw_text", ""),
    )
    if status == "new":
        result.new += 1
        result.new_ids.append(applicant_id)
        if SCREEN_ON_IMPORT:
            _screen_new(store, applicant_id, result)
    else:
        result.duplicates += 1


def _screen_new(
    store: SqliteApplicantStore, applicant_id: int, result: IngestResult
) -> None:
    from src.screening import screen_and_persist

    applicant = store.get(applicant_id)
    if applicant is None:
        return
    try:
        screen_and_persist(applicant, store)
        result.screened += 1
    except Exception as exc:  # noqa: BLE001 - one bad applicant must not abort ingest
        logger.warning("Auto-screening failed for applicant %s: %s", applicant_id, exc)
        result.errors.append(f"applicant {applicant_id}: screening failed: {exc}")


def _resolve_email(parsed_email: str | None, sender: str) -> str | None:
    if parsed_email and parsed_email != "unknown@domain.com":
        return parsed_email
    match = _SENDER_EMAIL_RE.search(sender or "")
    return match.group(0) if match else None
