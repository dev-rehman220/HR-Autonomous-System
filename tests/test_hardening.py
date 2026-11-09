"""Hardening regression tests: GitHub resilience, robust LLM parsing, guardrails."""
from __future__ import annotations

import types

import pytest
import requests

from src.graph import workflow
from src.guardrails import assert_no_salary, find_salary_leaks
from src.tools import github_evaluator


class _FakeResponse:
    def __init__(self, status_code: int = 200, payload: object | None = None, headers: dict | None = None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.headers = headers or {}

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(github_evaluator.time, "sleep", lambda *_: None)
    github_evaluator.clear_cache()


# --------------------------------------------------------------------------- #
# GitHub evaluator resilience
# --------------------------------------------------------------------------- #
def test_github_network_error_is_unverified(monkeypatch):
    def boom(*args, **kwargs):
        raise requests.RequestException("connection reset")

    monkeypatch.setattr(github_evaluator.requests, "get", boom)
    result = github_evaluator.evaluate_github_profile("octocat")
    assert result["verified"] is False
    assert "failed" in result["reason"].lower()


def test_github_429_is_rate_limited(monkeypatch):
    monkeypatch.setattr(
        github_evaluator.requests, "get", lambda *a, **k: _FakeResponse(429)
    )
    result = github_evaluator.evaluate_github_profile("octocat")
    assert "rate limit" in result["reason"].lower()


def test_github_403_with_remaining_budget_is_forbidden(monkeypatch):
    headers = {"X-RateLimit-Remaining": "42"}
    monkeypatch.setattr(
        github_evaluator.requests, "get", lambda *a, **k: _FakeResponse(403, headers=headers)
    )
    result = github_evaluator.evaluate_github_profile("octocat")
    assert "forbidden" in result["reason"].lower()


def test_github_forks_and_archived_are_ignored(monkeypatch):
    repos = [
        {"name": "fork", "language": "Ruby", "stargazers_count": 99,
         "pushed_at": "2999-01-01T00:00:00Z", "fork": True},
        {"name": "old", "language": "C", "stargazers_count": 50,
         "pushed_at": "2000-01-01T00:00:00Z", "archived": True},
        {"name": "mine", "language": "Python", "stargazers_count": 5,
         "pushed_at": "2999-01-01T00:00:00Z"},
    ]

    def fake_get(url, headers=None, params=None, timeout=None):
        if url.endswith("/repos"):
            return _FakeResponse(200, repos)
        return _FakeResponse(200, {"public_repos": 3})

    monkeypatch.setattr(github_evaluator.requests, "get", fake_get)
    result = github_evaluator.evaluate_github_profile("octocat")
    assert result["primary_languages"] == ["Python"]
    assert [project["name"] for project in result["pinned_projects"]] == ["mine"]
    assert result["recent_commit_activity"] is True


def test_github_cache_is_opt_in(monkeypatch):
    monkeypatch.setattr(github_evaluator, "GITHUB_CACHE_TTL", 60)
    calls = {"n": 0}

    def fake_get(url, headers=None, params=None, timeout=None):
        calls["n"] += 1
        if url.endswith("/repos"):
            return _FakeResponse(200, [])
        return _FakeResponse(200, {"public_repos": 1})

    monkeypatch.setattr(github_evaluator.requests, "get", fake_get)
    github_evaluator.evaluate_github_profile("octocat")
    github_evaluator.evaluate_github_profile("octocat")
    assert calls["n"] == 2  # user + repos, served from cache the second time


# --------------------------------------------------------------------------- #
# Robust LLM parsing
# --------------------------------------------------------------------------- #
def test_parse_evaluation_accepts_json_object():
    assert workflow._parse_evaluation('{"score": 91, "gaps": ["a", "b"]}') == (91, ["a", "b"])


def test_parse_evaluation_accepts_json_embedded_in_prose():
    text = 'Result: {"fit_score": "88/100", "gaps": "x | y"}'
    score, gaps = workflow._parse_evaluation(text)
    assert score == 88
    assert gaps == ["x", "y"]


def test_parse_evaluation_keeps_line_format_working():
    score, gaps = workflow._parse_evaluation("SCORE: 73\nGAPS: One | Two")
    assert score == 73
    assert gaps == ["One", "Two"]


def test_parse_evaluation_finds_loose_score_and_defaults():
    assert workflow._parse_evaluation("Overall fit score 64 out of 100")[0] == 64
    assert workflow._parse_evaluation("unparseable")[0] == 50


def test_evaluate_fit_survives_a_failing_llm(monkeypatch):
    class BoomLLM:
        def invoke(self, messages):
            raise RuntimeError("provider down")

    monkeypatch.setattr(workflow, "llm", BoomLLM())
    result = workflow.evaluate_fit_and_gaps(
        {"resume_text": "Python engineer", "matched_job": {}, "github_data": {}}
    )
    assert result["fit_score"] == 50
    assert result["gaps"]


def test_generate_questions_survives_a_failing_llm(monkeypatch):
    class BoomLLM:
        def invoke(self, messages):
            raise RuntimeError("provider down")

    monkeypatch.setattr(workflow, "llm", BoomLLM())
    result = workflow.generate_questions({"gaps": ["Testing"]})
    assert len(result["questions"]) >= 1


# --------------------------------------------------------------------------- #
# Salary guardrail
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "leak",
    ["$140,000", "$140k", "£140,000", "€95,000", "140,000 USD", "150k per year", "120k/yr"],
)
def test_find_salary_leaks_detects_common_formats(leak):
    assert find_salary_leaks(f"Compensation: {leak} base") != []


def test_assert_no_salary_clean_for_candidate_emails():
    clean = "We would like to invite you for a 45-minute technical screening call."
    assert assert_no_salary(clean)
    assert not assert_no_salary("Salary range $140,000 - $175,000")
