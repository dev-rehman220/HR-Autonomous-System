"""Streamlit UI: Gmail ingestion, applicant roster, and human-in-the-loop review.

Run from the project root:

    streamlit run src/app.py
"""
from __future__ import annotations

import os
import sys
import uuid

# Ensure the project root is importable when launched via `streamlit run src/app.py`.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import streamlit as st  # noqa: E402

from src.config import (  # noqa: E402
    EMAIL_SOURCE,
    GMAIL_LABEL,
    GMAIL_LOOKBACK_DAYS,
    GMAIL_MAX_RESULTS,
    GMAIL_QUERY,
    ROSTER_DB_PATH,
)
from src.graph.workflow import recruitment_agent  # noqa: E402
from src.ingest import IngestResult, build_email_source  # noqa: E402
from src.ingest.email_source import EmailSourceError  # noqa: E402
from src.ingest.pipeline import ingest  # noqa: E402
from src.logging_config import configure_logging  # noqa: E402
from src.roster.store import SqliteApplicantStore  # noqa: E402
from src.roster.taxonomy import get_specializations  # noqa: E402
from src.screening import screen_applicant  # noqa: E402
from src.tools.resume_parser import ResumeParseError, parse_resume  # noqa: E402

configure_logging()
st.set_page_config(page_title="TalentAgent Screener", layout="wide")
st.title("TalentAgent: Autonomous Technical Recruiter")


@st.cache_resource
def get_store() -> SqliteApplicantStore:
    return SqliteApplicantStore(ROSTER_DB_PATH)


def _initial_state(parsed: dict, github_handle: str | None) -> dict:
    return {
        "full_name": parsed.get("full_name", "Candidate"),
        "resume_text": parsed.get("raw_text", ""),
        "github_handle": github_handle,
        "matched_job": {},
        "github_data": {},
        "fit_score": 0,
        "gaps": [],
        "questions": [],
        "recruiter_slots": [],
        "draft_email": "",
        "decision": "",
    }


def _render_findings(state: dict) -> None:
    st.metric(label="Calculated Fit Score", value=f"{state.get('fit_score', 0)} / 100")
    job = state.get("matched_job", {})
    st.write(f"**Matched Role:** {job.get('title', 'N/A')} ({job.get('salary', 'N/A')})")
    st.write(f"**Decision:** {state.get('decision', 'N/A')}")

    with st.expander("Verified External Signals (GitHub Tool)", expanded=False):
        st.json(state.get("github_data", {}))

    with st.expander("Detected Gaps & Verification Questions", expanded=True):
        st.write("**Identified Gaps:**")
        for gap in state.get("gaps", []):
            st.write(f"- {gap}")
        st.write("**Screening Questions:**")
        for question in state.get("questions", []):
            st.info(question)

    slots = state.get("recruiter_slots", [])
    if slots:
        with st.expander("Available Recruiter Slots", expanded=False):
            for slot in slots:
                st.write(f"- {slot.get('display', slot.get('datetime_iso'))}")

    st.subheader("Human-In-The-Loop Action Dispatch")
    st.caption("Outbound communication stays in draft until you approve it (guardrail #3).")
    email_text = st.text_area(
        "Review/Edit Candidate Email", value=state.get("draft_email", ""), height=240
    )
    if st.button("Approve & Dispatch Communication"):
        st.session_state["approved_email"] = email_text
        st.success(
            f"Communication for decision '{state.get('decision')}' approved and dispatched."
        )


def _inbox_tab() -> None:
    store = get_store()
    st.subheader("Fetch applications from the configured mailbox")
    st.caption(
        "Manual, on-demand ingestion. The source is set by EMAIL_SOURCE "
        f"(currently **{EMAIL_SOURCE}**)."
    )

    col1, col2 = st.columns(2)
    with col1:
        source_name = st.selectbox(
            "Source", ["local", "mcp"], index=0 if EMAIL_SOURCE == "local" else 1
        )
        label = st.text_input("Gmail label (optional)", value=GMAIL_LABEL)
    with col2:
        query = st.text_input("Gmail query", value=GMAIL_QUERY)
        max_results = st.number_input("Max results", 1, 500, min(GMAIL_MAX_RESULTS, 500))

    lookback_days = st.number_input("Look back (days)", 1, 3650, GMAIL_LOOKBACK_DAYS)

    if st.button("Fetch & Ingest Applications"):
        try:
            source = build_email_source(source_name)
            result: IngestResult = ingest(
                source,
                store,
                label=label,
                query=query,
                max_results=int(max_results),
                lookback_days=int(lookback_days),
            )
        except EmailSourceError as exc:
            st.error(f"Ingestion failed: {exc}")
        else:
            st.success(result.summary)
            if result.errors:
                st.warning("Some attachments could not be processed:")
                for error in result.errors:
                    st.write(f"- {error}")

    st.divider()
    st.metric("Applicants in roster", store.count())


def _roster_tab() -> None:
    store = get_store()
    st.subheader("Applicant Roster — grouped by specialization, ranked by score")

    col1, col2, col3 = st.columns(3)
    with col1:
        specializations = st.multiselect(
            "Filter specializations", get_specializations(), default=get_specializations()
        )
    with col2:
        status_filter = st.selectbox(
            "Status", ["all", "new", "screened", "invited", "rejected"]
        )
    with col3:
        min_score = st.slider("Minimum score", 0, 100, 0)

    applicants = store.list(
        status=None if status_filter == "all" else status_filter,
        min_score=min_score,
    )
    if specializations:
        applicants = [a for a in applicants if a.get("specialization") in specializations]

    if not applicants:
        st.info("No applicants yet. Fetch from the Inbox tab or upload a resume manually.")
        return

    table = [
        {
            "id": a["id"],
            "name": a["full_name"],
            "specialization": a["specialization"],
            "score": a["fit_score"],
            "experience_years": a["experience_years"],
            "status": a["status"],
            "email": a["email"],
            "top_skills": ", ".join(a["skills"][:5]),
        }
        for a in applicants
    ]
    st.dataframe(table, width="stretch", hide_index=True)

    grouped: dict[str, list[dict]] = {}
    for applicant in applicants:
        grouped.setdefault(applicant.get("specialization") or "Other", []).append(applicant)

    for bucket, members in sorted(grouped.items()):
        with st.expander(f"{bucket} — {len(members)} applicant(s)", expanded=False):
            for member in sorted(members, key=lambda a: a["fit_score"], reverse=True):
                st.write(
                    f"**{member['full_name']}** · score {member['fit_score']} · "
                    f"{member['experience_years']} yrs · {member['status']}"
                )

    st.divider()
    st.subheader("Screen applicants with the agentic workflow")
    options = {
        f"#{a['id']} {a['full_name']} ({a['specialization']}, {a['fit_score']})": a["id"]
        for a in applicants
    }
    selected = st.multiselect("Select applicants to screen", list(options.keys()))
    if st.button("Run Screening on Selection") and selected:
        report: list[tuple[str, str]] = []
        for label_text in selected:
            applicant = store.get(options[label_text])
            if applicant is None:
                continue
            with st.spinner(f"Screening {applicant['full_name']}..."):
                try:
                    state = screen_applicant(applicant)
                except Exception as exc:  # noqa: BLE001 - surface, keep the UI alive
                    report.append((applicant["full_name"], f"error:{exc}"))
                    continue
                store.update_screening(applicant["id"], state)
            report.append(
                (
                    applicant["full_name"],
                    f"score {state.get('fit_score')} → {state.get('decision')}",
                )
            )
        st.session_state["screening_report"] = report
        st.rerun()

    for name, outcome in st.session_state.pop("screening_report", []):
        if outcome.startswith("error:"):
            st.error(f"{name}: screening failed — {outcome.removeprefix('error:')}")
        else:
            st.success(f"{name}: {outcome}")


def _manual_tab() -> None:
    col1, col2 = st.columns([1, 1])
    with col1:
        st.subheader("1. Candidate Ingestion")
        uploaded_file = st.file_uploader("Upload Candidate Resume (PDF)", type=["pdf"])
        manual_github = st.text_input("Override GitHub Username (optional)", value="")

        if uploaded_file and st.button("Run Multi-Step Agent Screening"):
            try:
                parsed = parse_resume(uploaded_file.read())
            except ResumeParseError as exc:
                st.error(f"Could not process this resume: {exc}")
                st.session_state.pop("agent_state", None)
            else:
                github_handle = manual_github.strip() or parsed.get("github_username")
                thread_id = f"{parsed.get('email', 'candidate')}-{uuid.uuid4().hex[:8]}"
                with st.spinner("Executing agentic workflow..."):
                    final_state = recruitment_agent.invoke(
                        _initial_state(parsed, github_handle),
                        config={"configurable": {"thread_id": thread_id}},
                    )
                st.session_state["agent_state"] = final_state
                st.session_state["thread_id"] = thread_id
                st.success("Screening pipeline completed!")

    with col2:
        st.subheader("2. Evaluation & Agent Findings")
        if "agent_state" in st.session_state:
            _render_findings(st.session_state["agent_state"])
        else:
            st.info("Upload a resume to run the screening pipeline.")


inbox_tab, roster_tab, manual_tab = st.tabs(
    ["Inbox Fetch", "Applicant Roster", "Manual Upload"]
)
with inbox_tab:
    _inbox_tab()
with roster_tab:
    _roster_tab()
with manual_tab:
    _manual_tab()
