"""Assign a canonical specialization to a parsed candidate."""
from __future__ import annotations

from src.roster.taxonomy import (
    classify_specialization,
    keyword_specialization,
    specialization_scores,
)


def classify(parsed: dict, text: str = "") -> tuple[str, float]:
    """Return (specialization, confidence) from skills, falling back to keywords."""
    scores = specialization_scores(list(parsed.get("skills") or []))
    specialization, confidence = classify_specialization(scores)
    if specialization == "Other" and text:
        return keyword_specialization(text)
    return specialization, confidence
