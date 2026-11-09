"""LangGraph state machine orchestrating the recruiting pipeline.

Flow (docs/05_sop_instructions.md):

    retrieve_job -> verify_signals -> evaluate_fit -> generate_questions
        -> (fit_score >= 70) draft_invite
        -> (fit_score <  70) draft_rejection

The graph is compiled with an in-memory checkpointer so a recruiter can revisit a
candidate's state across turns without reprocessing (FR-6).
"""
from __future__ import annotations

import json
import logging
import re
from typing import List, Optional, TypedDict

import chromadb
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from src.config import (
    CHROMA_PATH,
    COLLECTION_NAME,
    FALLBACK_API_KEY,
    FALLBACK_BASE_URL,
    FALLBACK_MODEL,
    FIT_THRESHOLD,
    OPENAI_BASE_URL,
    OPENAI_MODEL,
)
from src.guardrails import prepare_for_external
from src.tools.github_evaluator import evaluate_github_profile
from src.tools.scheduler import (
    draft_interview_email,
    draft_rejection_email,
    fetch_recruiter_schedule,
)

logger = logging.getLogger(__name__)

EVALUATION_CHAR_BUDGET = 2000


class CandidateState(TypedDict):
    """Shared state passed between graph nodes."""

    full_name: str
    resume_text: str
    github_handle: Optional[str]
    matched_job: dict
    github_data: dict
    fit_score: int
    gaps: List[str]
    questions: List[str]
    recruiter_slots: list
    draft_email: str
    decision: str


SYSTEM_PROMPT = (
    "You are TalentAgent, a strict, objective technical recruiting evaluator. "
    "Base every judgement on the supplied job requirements and resume evidence. "
    "Never infer or use age, gender, nationality, graduation year, or any other "
    "protected attribute. If evidence is missing, mark it as unverified rather "
    "than guessing."
)

FALLBACK_JOB: dict = {
    "job_id": "GENERIC",
    "title": "Software Engineer",
    "requirements": "Solid core programming skills and production engineering experience.",
    "required_skills": [],
    "min_experience_years": 0,
    "salary": "Standard",
}

DEFAULT_GAPS = ["Insufficient evidence to verify the claimed skill set"]

# Lazily constructed: importing this module must not require an OPENAI_API_KEY.
llm: Optional[Runnable] = None


def _build_chat_model(
    model: str, *, api_key: str | None = None, base_url: str | None = None
) -> ChatOpenAI:
    kwargs: dict = {
        "model": model,
        "temperature": 0.1,
        "timeout": 20,
        "max_retries": 1,
    }
    resolved_url = base_url or OPENAI_BASE_URL
    if resolved_url:
        kwargs["base_url"] = resolved_url
    if api_key:
        kwargs["api_key"] = api_key
    return ChatOpenAI(**kwargs)


def _split_models(value: str) -> list[str]:
    return [model.strip() for model in value.split(",") if model.strip()]


def get_llm() -> Runnable:
    """Return the (lazily created, cached) chat model."""
    global llm
    if llm is None:
        chain = [_build_chat_model(model) for model in _split_models(OPENAI_MODEL)]
        chain.extend(
            _build_chat_model(model, api_key=FALLBACK_API_KEY, base_url=FALLBACK_BASE_URL)
            for model in _split_models(FALLBACK_MODEL)
        )
        if not chain:
            raise RuntimeError("No LLM model configured (set OPENAI_MODEL).")
        llm = chain[0].with_fallbacks(chain[1:]) if len(chain) > 1 else chain[0]
    return llm


def _safe_invoke(prompt: str) -> Optional[str]:
    """Invoke the LLM, returning None (instead of raising) on any failure."""
    try:
        response = get_llm().invoke(
            [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=prompt)]
        )
    except Exception as exc:  # noqa: BLE001 - never let an LLM failure crash the graph
        logger.error("LLM invocation failed: %s", exc)
        return None
    content = getattr(response, "content", response)
    return str(content) if content is not None else None


# --------------------------------------------------------------------------- #
# Nodes
# --------------------------------------------------------------------------- #
def retrieve_job_requisition(state: CandidateState) -> dict:
    """RAG: find the closest active requisition for this resume (FR-2)."""
    query_text = (state.get("resume_text") or "").strip()[:1500] or "software engineer"
    matched = dict(FALLBACK_JOB)
    try:
        client = chromadb.PersistentClient(path=CHROMA_PATH)
        collection = client.get_or_create_collection(name=COLLECTION_NAME)
        results = collection.query(query_texts=[query_text], n_results=1)
        documents = (results.get("documents") or [[]])[0]
        metadatas = (results.get("metadatas") or [[]])[0]
        if documents:
            meta = metadatas[0] if metadatas else {}
            matched = {
                "job_id": meta.get("job_id", "UNKNOWN"),
                "title": meta.get("role", FALLBACK_JOB["title"]),
                "requirements": documents[0],
                "required_skills": [
                    skill.strip()
                    for skill in str(meta.get("required_skills", "")).split(",")
                    if skill.strip()
                ],
                "min_experience_years": meta.get("min_experience_years", 0),
                "salary": meta.get("salary_bracket", "Standard"),
            }
    except Exception as exc:  # noqa: BLE001 - retrieval failure must not crash the run
        logger.warning("Job retrieval failed, using fallback requisition: %s", exc)
        matched = dict(FALLBACK_JOB)
    return {"matched_job": matched}


def verify_candidate_signals(state: CandidateState) -> dict:
    """Verify claimed skills against public GitHub activity (FR-3)."""
    return {"github_data": evaluate_github_profile(state.get("github_handle"))}


def evaluate_fit_and_gaps(state: CandidateState) -> dict:
    """Score the candidate 0-100 and list concrete gaps (FR-2/FR-4)."""
    job = state.get("matched_job") or {}
    candidate_text = prepare_for_external(state.get("resume_text", ""))[:EVALUATION_CHAR_BUDGET]
    github_data = state.get("github_data") or {}
    prompt = (
        "Evaluate how well this candidate fits the role.\n\n"
        f"Job title: {job.get('title', FALLBACK_JOB['title'])}\n"
        f"Job requirements: {job.get('requirements', FALLBACK_JOB['requirements'])}\n"
        f"Candidate resume (PII removed): {candidate_text}\n"
        f"GitHub verification signals: {github_data}\n\n"
        "Respond in EXACTLY this format:\n"
        "SCORE: <integer between 0 and 100>\n"
        "GAPS: <gap 1> | <gap 2> | <gap 3>\n"
    )
    score, gaps = _parse_evaluation(_safe_invoke(prompt) or "")
    return {"fit_score": score, "gaps": gaps}


def generate_questions(state: CandidateState) -> dict:
    """Produce tailored technical screening questions targeting the gaps (FR-4)."""
    gaps = state.get("gaps") or []
    prompt = (
        "Write 3 concise, highly technical screening questions that probe the "
        "candidate's real experience in the following gap areas. Target production "
        "trade-offs, architecture decisions and edge cases. Return ONLY the numbered "
        "questions, one per line, with no preamble.\n\n"
        f"Gap areas: {', '.join(gaps)}"
    )
    return {"questions": _parse_questions(_safe_invoke(prompt) or "")}


def draft_invite(state: CandidateState) -> dict:
    """Draft an interview invitation with available recruiter slots (FR-5)."""
    name = state.get("full_name") or "Candidate"
    job_title = (state.get("matched_job") or {}).get("title", FALLBACK_JOB["title"])
    slots = fetch_recruiter_schedule()
    return {
        "decision": "INVITE",
        "recruiter_slots": slots,
        "draft_email": draft_interview_email(name, job_title, slots),
    }


def draft_rejection(state: CandidateState) -> dict:
    """Draft a respectful rejection notice (FR-5)."""
    name = state.get("full_name") or "Candidate"
    job_title = (state.get("matched_job") or {}).get("title", FALLBACK_JOB["title"])
    return {
        "decision": "REJECT",
        "recruiter_slots": [],
        "draft_email": draft_rejection_email(name, job_title),
    }


def route_decision(state: CandidateState) -> str:
    """Conditional router: 'invite' when the fit score clears the threshold."""
    return "invite" if state.get("fit_score", 0) >= FIT_THRESHOLD else "reject"


# --------------------------------------------------------------------------- #
# Parsing helpers (kept small and unit tested)
# --------------------------------------------------------------------------- #
def _clamp_score(value) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return max(0, min(100, int(value)))
    match = re.search(r"\d+", str(value))
    if not match:
        return None
    return max(0, min(100, int(match.group(0))))


def _try_json(text: str) -> Optional[object]:
    stripped = (text or "").strip()
    if not stripped:
        return None
    try:
        return json.loads(stripped)
    except (ValueError, TypeError):
        pass
    start, end = stripped.find("{"), stripped.rfind("}")
    if 0 <= start < end:
        try:
            return json.loads(stripped[start : end + 1])
        except (ValueError, TypeError):
            return None
    return None


def _coerce_gaps(raw) -> list[str]:
    if isinstance(raw, list):
        return [str(gap).strip() for gap in raw if str(gap).strip()]
    if isinstance(raw, str):
        return [gap.strip() for gap in re.split(r"[|\n]", raw) if gap.strip()]
    return []


def _parse_evaluation(text: str) -> tuple[int, list[str]]:
    payload = _try_json(text)
    if isinstance(payload, dict):
        score = _clamp_score(payload.get("score", payload.get("fit_score")))
        gaps = _coerce_gaps(payload.get("gaps"))
        if score is not None:
            return score, gaps or list(DEFAULT_GAPS)

    score: Optional[int] = None
    gaps: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        upper = line.upper()
        if upper.startswith("SCORE:"):
            digits = re.findall(r"\d+", line)
            if digits:
                score = _clamp_score(digits[0])
        elif upper.startswith("GAPS:"):
            gaps = [gap.strip() for gap in line.split(":", 1)[1].split("|") if gap.strip()]

    if score is None:
        match = re.search(r"(?:score|fit)\D{0,12}(\d{1,3})", text, re.IGNORECASE)
        score = _clamp_score(match.group(1)) if match else 50
    return score, gaps or list(DEFAULT_GAPS)


def _parse_questions(text: str) -> list[str]:
    questions: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = re.match(r"^(?:\d+[.)]|[-*])\s*(.+)$", line)
        if match:
            questions.append(match.group(1).strip())
    if not questions:
        questions = [line.strip() for line in text.splitlines() if line.strip()][:3]
    if not questions:
        questions = ["Describe a production system you built end-to-end and its key trade-offs."]
    return questions[:5]


# --------------------------------------------------------------------------- #
# Graph assembly
# --------------------------------------------------------------------------- #
def build_graph():
    """Build and compile the recruiting state machine (with memory checkpointer)."""
    builder = StateGraph(CandidateState)
    builder.add_node("retrieve_job", retrieve_job_requisition)
    builder.add_node("verify_signals", verify_candidate_signals)
    builder.add_node("evaluate_fit", evaluate_fit_and_gaps)
    builder.add_node("generate_questions", generate_questions)
    builder.add_node("draft_invite", draft_invite)
    builder.add_node("draft_rejection", draft_rejection)

    builder.add_edge(START, "retrieve_job")
    builder.add_edge("retrieve_job", "verify_signals")
    builder.add_edge("verify_signals", "evaluate_fit")
    builder.add_edge("evaluate_fit", "generate_questions")
    builder.add_conditional_edges(
        "generate_questions",
        route_decision,
        {"invite": "draft_invite", "reject": "draft_rejection"},
    )
    builder.add_edge("draft_invite", END)
    builder.add_edge("draft_rejection", END)

    return builder.compile(checkpointer=MemorySaver())


# Module-level compiled agent reused by the Streamlit app.
recruitment_agent = build_graph()
