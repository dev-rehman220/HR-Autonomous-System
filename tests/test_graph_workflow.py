"""Workflow tests: state transitions, conditional branching and memory (Phase 4).

The LLM, the ChromaDB client and the GitHub tool are all faked so the graph can
be exercised deterministically without network access or an OpenAI key.
Covers TC-01, TC-02, TC-03 and FR-6 (stateful memory).
"""
from __future__ import annotations

import types
import uuid

import pytest

from src.graph import workflow

VERIFIED_GITHUB = {
    "user_exists": True,
    "username": "janedoe",
    "public_repos": 9,
    "primary_languages": ["Python", "Go"],
    "pinned_projects": [{"name": "agent", "stars": 42}],
    "recent_commit_activity": True,
    "verified": True,
    "reason": None,
}

UNVERIFIED_GITHUB = {
    "user_exists": False,
    "public_repos": 0,
    "primary_languages": [],
    "pinned_projects": [],
    "recent_commit_activity": False,
    "verified": False,
    "reason": "No GitHub handle provided",
}

DEFAULT_METADATA = {
    "job_id": "JOB-101",
    "role": "Senior Backend Engineer (Python/Cloud)",
    "required_skills": "Python, FastAPI, Docker, AWS",
    "min_experience_years": 4,
    "salary_bracket": "$140,000 - $175,000",
}


class FakeLLM:
    """A scripted chat model: emits SCORE/GAPS or numbered questions by intent."""

    def __init__(self, score: int = 85):
        self.score = score

    def invoke(self, messages):
        prompt = messages[-1].content
        if "SCORE:" in prompt:
            return types.SimpleNamespace(
                content=f"SCORE: {self.score}\nGAPS: Cloud deployment | Query tuning | Testing"
            )
        return types.SimpleNamespace(
            content="1. Describe a system you built.?\n2. How do you tune queries?\n3. Explain a trade-off."
        )


class FakeCollection:
    def __init__(self, document: str, metadata: dict):
        self._document = document
        self._metadata = metadata

    def query(self, query_texts=None, n_results=1):
        return {"documents": [[self._document]], "metadatas": [[self._metadata]]}


class FakeClient:
    def __init__(self, document: str, metadata: dict):
        self._document = document
        self._metadata = metadata

    def get_or_create_collection(self, name=None):
        return FakeCollection(self._document, self._metadata)


@pytest.fixture
def run_graph(monkeypatch):
    """Return a runner that fakes all external edges and executes the graph."""

    def _run(score: int = 85, github: dict | None = None):
        monkeypatch.setattr(workflow, "llm", FakeLLM(score=score))
        monkeypatch.setattr(
            workflow.chromadb,
            "PersistentClient",
            lambda path=None: FakeClient(
                "Python FastAPI Docker AWS distributed backend role", DEFAULT_METADATA
            ),
        )
        monkeypatch.setattr(
            workflow,
            "evaluate_github_profile",
            lambda username: github if github is not None else dict(UNVERIFIED_GITHUB),
        )

        agent = workflow.build_graph()
        state = {
            "full_name": "Jane Doe",
            "resume_text": "Python FastAPI Docker AWS PostgreSQL 6 years building services",
            "github_handle": "janedoe",
            "matched_job": {},
            "github_data": {},
            "fit_score": 0,
            "gaps": [],
            "questions": [],
            "recruiter_slots": [],
            "draft_email": "",
            "decision": "",
        }
        config = {"configurable": {"thread_id": f"test-{uuid.uuid4().hex}"}}
        return agent.invoke(state, config=config), agent, config

    return _run


def test_strong_candidate_is_invited(run_graph):
    # TC-01: matching skills + verified GitHub -> INVITE with slots.
    result, _, _ = run_graph(score=85, github=VERIFIED_GITHUB)
    assert result["decision"] == "INVITE"
    assert result["fit_score"] == 85
    assert result["recruiter_slots"]
    assert "Interview Invitation" in result["draft_email"]
    assert result["matched_job"]["job_id"] == "JOB-101"
    assert len(result["questions"]) == 3
    assert result["gaps"] == ["Cloud deployment", "Query tuning", "Testing"]


def test_candidate_without_github_still_completes(run_graph):
    # TC-02: no GitHub handle -> skip verification, still score and complete.
    result, _, _ = run_graph(score=80, github=None)
    assert result["github_data"]["verified"] is False
    assert result["decision"] == "INVITE"
    assert result["draft_email"]


def test_unqualified_candidate_is_rejected(run_graph):
    # TC-03: below-threshold score -> REJECT, no slots.
    result, _, _ = run_graph(score=55)
    assert result["decision"] == "REJECT"
    assert result["recruiter_slots"] == []
    assert "Update regarding your application" in result["draft_email"]


def test_route_decision_threshold_is_inclusive():
    assert workflow.route_decision({"fit_score": 70}) == "invite"
    assert workflow.route_decision({"fit_score": 69}) == "reject"
    assert workflow.route_decision({}) == "reject"


def test_parse_evaluation_falls_back_when_unstructured():
    score, gaps = workflow._parse_evaluation("no structured output here")
    assert score == 50
    assert gaps


def test_parse_questions_extracts_numbered_and_bulleted_lines():
    assert workflow._parse_questions("1. One?\n2. Two?\n- Three?") == ["One?", "Two?", "Three?"]


def test_state_is_retained_by_the_checkpointer(run_graph):
    # FR-6: compiled with MemorySaver, state is retrievable for a thread.
    result, agent, config = run_graph(score=85, github=VERIFIED_GITHUB)
    snapshot = agent.get_state(config)
    assert snapshot.values["decision"] == "INVITE"
    assert snapshot.values["fit_score"] == 85
