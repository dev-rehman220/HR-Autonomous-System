# Autonomous Execution Plan: Technical Recruitment & Screening Agent

## Mission Objective
Build, integrate, and verify an end-to-end Agentic HR system matching the academic specification:
1. Multi-step LangGraph workflow with autonomous decision branching.
2. At least 3 integrated tools (PDF Resume Parser, GitHub Profile Evaluator, Recruiter Scheduler).
3. Grounded Knowledge Retrieval (RAG) using persistent ChromaDB for job requisitions and salary bands.
4. Human-in-the-loop review interface built with Streamlit.

---

## Phase 1: Environment & Dependency Initialization
- [ ] **Step 1.1:** Create a Python virtual environment (`python -m venv venv`).
- [ ] **Step 1.2:** Activate the environment and install dependencies from `requirements.txt`:
  ```bash
  pip install --upgrade pip
  pip install -r requirements.txt
  ```
  - [ ] **Step 1.3:** Verify environment variables in `.env`:
    - `OPENAI_API_KEY`: Required for LLM routing and evaluation nodes.
    - `GITHUB_TOKEN`: Optional (to bypass unauthenticated rate limits on GitHub REST API).
- [ ] **Step 1.4:** Create project directory structure:
  ```bash
  mkdir -p docs config scripts src/tools src/graph tests chroma_db
  ```

---

## Phase 2: Knowledge Base & RAG Setup
- [ ] **Step 2.1:** Implement `scripts/seed_chroma.py`.
  - Populate at least 3 distinct technical job requisitions (`JOB-101`, `JOB-102`, `JOB-103`).
  - Store role title, required competencies, and salary ranges in document metadata.
- [ ] **Step 2.2:** Execute seed script:
  ```bash
  python scripts/seed_chroma.py
  ```
- [ ] **Step 2.3:** Verify ChromaDB storage created at `./chroma_db`.

---

## Phase 3: Tool Implementation & Isolation Testing
- [ ] **Step 3.1: Resume Parser Tool (`src/tools/resume_parser.py`)**
  - Implement `parse_resume(file_bytes: bytes) -> dict`.
  - Extract text via `pypdf`, run regex patterns for candidate email, full name, and GitHub URL.
  - Extract declared skill matches against baseline technical stacks.
- [ ] **Step 3.2: GitHub Evaluator Tool (`src/tools/github_evaluator.py`)**
  - Implement `evaluate_github_profile(username: str) -> dict`.
  - Query public GitHub REST API for total repositories, primary languages, and recent activity.
  - Implement fallback handling for missing handles or non-200 responses.
- [ ] **Step 3.3: Scheduler & Dispatch Tool (`src/tools/scheduler.py`)**
  - Implement `fetch_recruiter_schedule(recruiter_id: str) -> list`.
  - Implement `draft_interview_email(candidate_name, job_title, slots) -> str`.
  - Implement `draft_rejection_email(candidate_name, job_title) -> str`.
- [ ] **Step 3.4:** Write and run isolated tool tests:
  ```bash
  pytest tests/test_tools.py -v
  ```

---

## Phase 4: LangGraph Agent Workflow Implementation
- [ ] **Step 4.1:** Define `CandidateState` schema in `src/graph/workflow.py` with fields:
  - `full_name`, `resume_text`, `github_handle`, `matched_job`, `github_data`, `fit_score`, `gaps`, `questions`, `recruiter_slots`, `draft_email`, `decision`.
- [ ] **Step 4.2:** Implement Graph Nodes:
  - `retrieve_job`: Queries ChromaDB collection with resume text to extract the matching JD.
  - `verify_signals`: Invokes `evaluate_github_profile` tool.
  - `evaluate_fit`: Prompts LLM to calculate fit score (0-100) and pinpoint 2-3 specific technical gaps.
  - `generate_questions`: Prompts LLM to write 3 diagnostic screening questions targeted at the identified gaps.
  - `draft_communication`: Routes based on fit score (`>= 70` fetches slots and drafts interview invite; `< 70` drafts rejection).
- [ ] **Step 4.3:** Connect nodes using `StateGraph` and compile into `recruitment_agent`.
- [ ] **Step 4.4:** Test state transitions and branching:
  ```bash
  pytest tests/test_graph_workflow.py -v
  ```

---

## Phase 5: Streamlit Interface & Human-in-the-Loop Integration
- [ ] **Step 5.1:** Implement UI layout in `src/app.py`:
  - **Left Panel:** Resume file uploader (`.pdf`), manual GitHub override field, execution trigger button.
  - **Right Panel:** Fit score metric, matched job & salary details, verified GitHub signals accordion, generated screening questions.
- [ ] **Step 5.2:** Add editable text area for candidate email review.
- [ ] **Step 5.3:** Implement "Approve & Dispatch" button to simulate final human confirmation before action.

---

## Phase 6: End-to-End Evaluation & Verification Loop
- [ ] **Step 6.1:** Run full automated test suite:
  ```bash
  pytest --cov=src tests/ -v
  ```
- [ ] **Step 6.2:** Execute manual verification against test scenarios:
  1. *Strong Candidate:* Ingest resume with matching skills and active GitHub -> Ensure fit score >= 70, interview invite drafted with slots.
  2. *Gap Candidate:* Ingest resume missing key framework experience -> Verify questions specifically target missing skills.
  3. *Unqualified Candidate:* Ingest non-matching resume -> Ensure fit score < 70, polite rejection email drafted.
- [ ] **Step 6.3:** Launch local development server to confirm viva demonstration readiness:
  ```bash
  streamlit run src/app.py
  ```
