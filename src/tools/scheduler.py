"""Scheduling & Dispatch Tool (FR-5).

Generates mock recruiter availability and drafts the candidate-facing emails.
In a production deployment `fetch_recruiter_schedule` would call a calendar
provider (Google Calendar / Outlook); the interface here is what the graph and
UI depend on.

Guardrail (docs/08 #4): candidate-facing drafts must never contain internal
salary figures, so none of the email templates include a compensation range.
"""
from __future__ import annotations

from datetime import datetime, timedelta


def fetch_recruiter_schedule(
    recruiter_id: str = "recruiter_01", now: datetime | None = None
) -> list[dict]:
    """Return the next three weekday 10:00 availability slots for a recruiter."""
    slots: list[dict] = []
    cursor = (now or datetime.now()) + timedelta(days=1)
    while len(slots) < 3:
        if cursor.weekday() < 5:  # Monday–Friday only
            slot_time = cursor.replace(hour=10, minute=0, second=0, microsecond=0)
            slots.append(
                {
                    "slot_id": f"{recruiter_id}_slot_{len(slots) + 1}",
                    "datetime_iso": slot_time.isoformat(),
                    "display": slot_time.strftime("%A, %b %d at %I:%M %p"),
                }
            )
        cursor += timedelta(days=1)
    return slots


def draft_interview_email(candidate_name: str, job_title: str, slots: list[dict]) -> str:
    """Draft an interview invitation listing the available recruiter slots."""
    formatted_slots = "\n".join(
        f"- {slot.get('display', slot.get('datetime_iso'))}" for slot in slots
    )
    return (
        f"Subject: Interview Invitation: {job_title} at Our Team\n\n"
        f"Dear {candidate_name},\n\n"
        f"Thank you for applying for the {job_title} position. Our hiring team has "
        f"reviewed your background and verified credentials, and we would like to "
        f"invite you for a 45-minute technical screening call.\n\n"
        f"Please reply with which of the following times works best for you:\n"
        f"{formatted_slots}\n\n"
        f"Best regards,\n"
        f"Talent Acquisition Team"
    )


def draft_rejection_email(candidate_name: str, job_title: str) -> str:
    """Draft a respectful rejection notice (no scheduling details included)."""
    return (
        f"Subject: Update regarding your application for {job_title}\n\n"
        f"Dear {candidate_name},\n\n"
        f"Thank you for taking the time to share your background with us. While your "
        f"experience is impressive, we have decided to proceed with other candidates "
        f"whose skill profile more closely matches the immediate requirements of this role.\n\n"
        f"We will retain your profile for future opportunities that align with your background.\n\n"
        f"Best regards,\n"
        f"Talent Acquisition Team"
    )
