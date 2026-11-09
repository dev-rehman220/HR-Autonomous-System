"""Roster tests: taxonomy classification, SQLite store dedup, and ranking."""
from __future__ import annotations

from src.roster.classifier import classify
from src.roster.ranking import (
    group_by_specialization,
    heuristic_match_score,
    profile_strength_score,
    rank,
    top_candidates,
)
from src.roster.store import SqliteApplicantStore, normalize_email
from src.roster.taxonomy import (
    classify_specialization,
    get_specializations,
    keyword_specialization,
    specialization_scores,
)


# --------------------------------------------------------------------------- #
# Taxonomy & classifier
# --------------------------------------------------------------------------- #
def test_backend_skills_classify_as_backend():
    scores = specialization_scores(["Python", "FastAPI", "PostgreSQL"])
    assert classify_specialization(scores)[0] == "Backend"


def test_frontend_and_backend_classify_as_full_stack():
    assert classify({"skills": ["React", "TypeScript", "Python", "Django"]})[0] == "Full-Stack"


def test_ml_skills_classify_as_ml_ai():
    assert classify({"skills": ["PyTorch", "LangChain", "RAG"]})[0] == "ML/AI"


def test_unknown_skills_fall_back_to_keywords_then_other():
    assert classify({}, text="Experienced data engineer with Spark")[0] == "Data"
    assert classify({}, text="nothing recognizable")[0] == "Other"


def test_keyword_specialization_matches_role_phrases():
    assert keyword_specialization("Site Reliability Engineer")[0] == "DevOps/Cloud"


def test_get_specializations_always_includes_other():
    assert "Other" in get_specializations()


# --------------------------------------------------------------------------- #
# Ranking
# --------------------------------------------------------------------------- #
def test_profile_strength_score_is_bounded():
    assert profile_strength_score([], 0) == 0
    assert 0 <= profile_strength_score(["Python"], 1) <= 100
    assert profile_strength_score([f"skill{i}" for i in range(20)], 20) == 100


def test_heuristic_match_score_rewards_skill_coverage():
    strong = heuristic_match_score(["Python", "FastAPI", "AWS"], 5, ["Python", "FastAPI", "AWS"], 4)
    weak = heuristic_match_score(["Php"], 1, ["Python", "FastAPI", "AWS"], 4)
    assert strong > weak


def test_rank_and_group_helpers_order_descending():
    rows = [
        {"name": "a", "fit_score": 30, "specialization": "Backend"},
        {"name": "b", "fit_score": 90, "specialization": "Backend"},
        {"name": "c", "fit_score": 50, "specialization": "ML/AI"},
    ]
    assert [row["name"] for row in rank(rows)][0] == "b"
    grouped = group_by_specialization(rows)
    assert grouped["Backend"][0]["name"] == "b"
    assert top_candidates(rows, limit=1)[0]["name"] == "b"


# --------------------------------------------------------------------------- #
# Store
# --------------------------------------------------------------------------- #
def test_normalize_email_lowercases_and_drops_unknown():
    assert normalize_email("Jane.Doe@Example.com") == "jane.doe@example.com"
    assert normalize_email("unknown@domain.com") is None
    assert normalize_email("not-an-email") is None


def test_upsert_inserts_then_dedups_by_hash_email_and_message():
    store = SqliteApplicantStore(":memory:")
    status, first_id = store.upsert_candidate(
        full_name="Jane Doe", email="jane@example.com", specialization="Backend",
        skills=["Python"], experience_years=5, cv_hash="hash-1", message_id="msg-1",
    )
    assert status == "new"

    assert store.upsert_candidate(full_name="Jane", cv_hash="hash-1")[0] == "duplicate"
    assert store.upsert_candidate(full_name="Jane", email="JANE@example.com")[0] == "duplicate"
    assert store.upsert_candidate(full_name="Jane", message_id="msg-1")[0] == "duplicate"
    assert store.count() == 1
    assert store.get(first_id)["seen_count"] == 4
    store.close()


def test_store_list_filters_and_grouping():
    store = SqliteApplicantStore(":memory:")
    store.upsert_candidate(full_name="A", specialization="Backend", fit_score=80, cv_hash="a")
    store.upsert_candidate(full_name="B", specialization="ML/AI", fit_score=40, cv_hash="b")
    store.upsert_candidate(full_name="C", specialization="Backend", fit_score=60, cv_hash="c")

    backends = store.list(specialization="Backend")
    assert [row["full_name"] for row in backends] == ["A", "C"]
    assert [row["full_name"] for row in store.list(min_score=50)] == ["A", "C"]
    grouped = store.group_by_specialization()
    assert len(grouped["Backend"]) == 2
    assert grouped["Backend"][0]["full_name"] == "A"
    store.close()


def test_store_update_screening_sets_status_and_decision():
    store = SqliteApplicantStore(":memory:")
    _, applicant_id = store.upsert_candidate(full_name="A", cv_hash="a")
    store.update_screening(
        applicant_id,
        {
            "fit_score": 88,
            "decision": "INVITE",
            "gaps": ["Testing"],
            "questions": ["Q1", "Q2"],
            "draft_email": "Subject: hi",
            "matched_job": {"job_id": "JOB-101"},
        },
    )
    row = store.get(applicant_id)
    assert row["status"] == "invited"
    assert row["fit_score"] == 88
    assert row["gaps"] == ["Testing"]
    assert row["matched_job_id"] == "JOB-101"
    store.close()


def test_store_reject_marks_rejected():
    store = SqliteApplicantStore(":memory:")
    _, applicant_id = store.upsert_candidate(full_name="A", cv_hash="a")
    store.update_screening(applicant_id, {"decision": "REJECT"})
    assert store.get(applicant_id)["status"] == "rejected"
    store.close()


def test_store_delete_removes_row():
    store = SqliteApplicantStore(":memory:")
    _, applicant_id = store.upsert_candidate(full_name="A", cv_hash="a")
    store.delete(applicant_id)
    assert store.get(applicant_id) is None
    store.close()
