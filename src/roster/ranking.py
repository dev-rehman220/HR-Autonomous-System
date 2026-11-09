"""Heuristic scoring and ordering helpers for the applicant roster."""
from __future__ import annotations

from typing import Optional

DEFAULT_ORDER_COLUMNS = ("fit_score", "experience_years")


def profile_strength_score(skills: list[str], experience_years: float) -> int:
    """Quick, LLM-free score used at ingest time to seed roster ordering."""
    breadth = min(len([skill for skill in skills or [] if skill]) / 12.0, 1.0)
    depth = min(max(float(experience_years or 0.0), 0.0) / 8.0, 1.0)
    return round(100 * (0.6 * breadth + 0.4 * depth))


def heuristic_match_score(
    skills: list[str],
    experience_years: float,
    required_skills: list[str],
    min_experience_years: float = 0,
) -> int:
    """Rough fit score against a requisition without calling the LLM."""
    required = {skill.strip().lower() for skill in (required_skills or []) if skill.strip()}
    have = {skill.strip().lower() for skill in (skills or []) if skill.strip()}
    coverage = len(required & have) / len(required) if required else min(len(have) / 10.0, 1.0)
    if min_experience_years and min_experience_years > 0:
        experience = min(max(float(experience_years or 0.0), 0.0) / min_experience_years, 1.0)
    else:
        experience = 1.0 if experience_years else 0.5
    return round(100 * (0.7 * coverage + 0.3 * experience))


def rank(
    applicants: list[dict], *, by: str = "fit_score", descending: bool = True
) -> list[dict]:
    column = by if by in DEFAULT_ORDER_COLUMNS or by == "full_name" else "fit_score"
    return sorted(
        applicants or [],
        key=lambda applicant: (applicant.get(column) is None, applicant.get(column) or 0),
        reverse=descending,
    )


def group_by_specialization(
    applicants: list[dict], *, by: str = "fit_score", descending: bool = True
) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for applicant in applicants or []:
        bucket = applicant.get("specialization") or "Other"
        grouped.setdefault(bucket, []).append(applicant)
    return {bucket: rank(items, by=by, descending=descending) for bucket, items in grouped.items()}


def top_candidates(applicants: list[dict], limit: int = 5) -> list[dict]:
    return rank(applicants)[: max(0, int(limit))]
