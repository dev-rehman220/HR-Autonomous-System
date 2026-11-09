"""Applicant roster: persistent store, specialization taxonomy, ranking."""
from src.roster.classifier import classify
from src.roster.ranking import (
    group_by_specialization,
    heuristic_match_score,
    profile_strength_score,
    rank,
    top_candidates,
)
from src.roster.store import SqliteApplicantStore, normalize_email
from src.roster.taxonomy import get_specializations

__all__ = [
    "SqliteApplicantStore",
    "normalize_email",
    "classify",
    "get_specializations",
    "profile_strength_score",
    "heuristic_match_score",
    "rank",
    "group_by_specialization",
    "top_candidates",
]
