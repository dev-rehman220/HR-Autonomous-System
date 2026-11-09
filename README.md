# TalentAgent — Autonomous HR / Technical Recruiter

An agentic screening pipeline: a LangGraph state machine parses resumes, verifies
external signals through tools (GitHub, real calendar slots, ChromaDB job
matching), applies salary/hard-gate guardrails, and produces a score, gap list,
screening questions and a human-in-the-loop email draft.

Ingestion and roster layers sit **on top** of that engine:

| Layer | Role |
| --- | --- |
| `src/ingest/` | Fetch application emails (local `.eml` mailbox or a Gmail MCP server), extract CV attachments, dedup |
| `src/roster/` | Persistent SQLite applicant store + fixed specialization taxonomy + ranking |
| `src/screening.py` | Bridges a roster row into the existing `CandidateState` graph |
| `src/graph/workflow.py` | The original screen-one-candidate engine (unchanged contract) |

## Setup

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env         # add OPENAI_API_KEY
python scripts/seed_chroma.py
```

`python-docx`, `striprtf` and `mcp` are required for DOCX/RTF extraction and the
Gmail MCP source respectively.

## Run

```bash
streamlit run src/app.py --server.port 8501   # UI: Inbox Fetch / Roster / Manual Upload
python scripts/fetch_inbox.py --source local  # headless ingest
```

Seed a demo mailbox with `python scripts/generate_sample_mailbox.py` (writes
`tests/fixtures/mail/*.eml`), then set `EMAIL_SOURCE=local`.

### Ingestion

`EMAIL_SOURCE=local` reads `LOCAL_MAILBOX_PATH` (no Gmail account needed);
`EMAIL_SOURCE=mcp` connects to your MCP server (`GMAIL_MCP_COMMAND` or
`GMAIL_MCP_URL`). The adapter expects the search tool to accept
`{"query", "maxResults"}` and return JSON text `{"messages":[...]}` with
base64 attachments — it auto-discovers the tool name via `tools/list` unless
`GMAIL_MCP_SEARCH_TOOL` is set.

Every message is deduplicated on `cv_hash`, `message_id` and normalized email.
CVs are parsed from PDF, DOCX, TXT and RTF. Ingestion is cheap and offline;
the agentic screening runs on demand from the Roster tab (or via
`SCREEN_ON_IMPORT=true`).

### Roster

Applicants are classified against a fixed taxonomy (Backend, Frontend,
Full-Stack, ML/AI, Data, DevOps/Cloud, Mobile, QA, Security, Other), ranked by
`heuristic_match_score` (skills + experience) and `profile_strength_score`
(resume completeness), then grouped for review. `src/roster/taxonomy.py` can be
overridden with `TAXONOMY_OVERRIDE`.

## Testing

```bash
pytest tests/ -q        # 95 tests: tools, workflow, ingest, roster, hardening, UI
```

## Hardening notes

- `FIT_THRESHOLD` is env-driven (0–100): at or above it the decision is INVITE, otherwise REJECT.
- LLM output parsing is JSON-first with a line-format fallback; a provider
  failure degrades to score 50 + default gap list instead of an exception.
- GitHub tool: backoff on 403/429, forks/archived repos excluded, top-3 pinned
  projects, opt-in TTL cache (`GITHUB_CACHE_TTL`, default 0 = always fresh).
- Resume parsing caps pages and text length; salary guardrail matches
  `$140k`, `£140,000`, `140,000 USD`, `150k per year`, etc.

## Docs

Full PRD, tool API specs, guardrails and SOPs live in [`docs/`](docs/):
`01_problem_scope.md` … `09_eval_testing_suite.md`.
# HR-Autonomous-System
