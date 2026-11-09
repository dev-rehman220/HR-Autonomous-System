"""Screening bridge tests: roster row -> CandidateState -> persisted result."""
from __future__ import annotations

from src.roster.store import SqliteApplicantStore
from src.screening import applicant_to_state, screen_and_persist, screen_applicant


def test_applicant_to_state_maps_row_and_defaults():
    state = applicant_to_state(
        {"full_name": "Jane", "resume_text": "Python engineer", "github_username": "janedoe"}
    )
    assert state["full_name"] == "Jane"
    assert state["resume_text"] == "Python engineer"
    assert state["github_handle"] == "janedoe"
    assert state["matched_job"] == {}
    assert state["fit_score"] == 0
    assert state["gaps"] == []
    assert state["decision"] == ""


def test_applicant_to_state_survives_a_sparse_row():
    state = applicant_to_state({})
    assert state["full_name"] == "Candidate"
    assert state["resume_text"] == ""
    assert state["github_handle"] is None


class _FakeAgent:
    def __init__(self):
        self.seen_state = None
        self.seen_config = None

    def invoke(self, state, config=None):
        self.seen_state = state
        self.seen_config = config
        return {**state, "fit_score": 91, "decision": "INVITE"}


def test_screen_applicant_passes_state_and_thread_id():
    agent = _FakeAgent()
    result = screen_applicant({"id": 7, "full_name": "Jane"}, agent=agent, thread_id="t-1")

    assert result["fit_score"] == 91
    assert agent.seen_state["full_name"] == "Jane"
    assert agent.seen_config == {"configurable": {"thread_id": "t-1"}}


def test_screen_applicant_generates_a_thread_id_when_omitted():
    agent = _FakeAgent()
    screen_applicant({"id": 7}, agent=agent)
    thread_id = agent.seen_config["configurable"]["thread_id"]
    assert thread_id.startswith("applicant-7-")
    assert len(thread_id) > len("applicant-7-")


def test_screen_and_persist_writes_results_back_to_the_store():
    store = SqliteApplicantStore(":memory:")
    _, applicant_id = store.upsert_candidate(full_name="Jane", cv_hash="h1")
    applicant = store.get(applicant_id)

    state = screen_and_persist(applicant, store, agent=_FakeAgent())

    refreshed = store.get(applicant_id)
    assert refreshed["fit_score"] == 91
    assert refreshed["status"] == "invited"
    assert refreshed["decision"] == state["decision"]
    store.close()
