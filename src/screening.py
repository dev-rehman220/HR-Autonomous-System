"""Bridge a stored applicant into the existing screening graph (FR-2..FR-7)."""
from __future__ import annotations

import uuid
from typing import Optional

from src.graph.workflow import recruitment_agent
from src.roster.store import SqliteApplicantStore


def applicant_to_state(applicant: dict) -> dict:
    """Build the initial `CandidateState` for the LangGraph workflow from a row."""
    return {
        "full_name": applicant.get("full_name") or "Candidate",
        "resume_text": applicant.get("resume_text") or "",
        "github_handle": applicant.get("github_username"),
        "matched_job": {},
        "github_data": {},
        "fit_score": 0,
        "gaps": [],
        "questions": [],
        "recruiter_slots": [],
        "draft_email": "",
        "decision": "",
    }


def screen_applicant(applicant: dict, agent=None, thread_id: Optional[str] = None) -> dict:
    """Run the screening workflow for one applicant and return the final state."""
    agent = agent or recruitment_agent
    resolved_thread = thread_id or f"applicant-{applicant.get('id', '?')}-{uuid.uuid4().hex[:8]}"
    return agent.invoke(
        applicant_to_state(applicant),
        config={"configurable": {"thread_id": resolved_thread}},
    )


def screen_and_persist(applicant: dict, store: SqliteApplicantStore, agent=None) -> dict:
    """Screen an applicant and write the results back to the roster."""
    state = screen_applicant(applicant, agent=agent)
    store.update_screening(int(applicant["id"]), state)
    return state
