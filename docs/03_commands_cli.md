# Commands & CLI Specification

## 1. Environment & Setup
```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env       # set OPENAI_API_KEY (and ingestion settings)
```

## 2. Seed Vector Database
```bash
python scripts/seed_chroma.py
```

## 3. Automated Test Suite
```bash
pytest tests/test_tools.py -v
pytest tests/test_graph_workflow.py -v
pytest --cov=src tests/ -v
```

## 4. Run UI Application
```bash
streamlit run src/app.py --server.port 8501
```
Tabs: **Inbox Fetch** (ingest mailbox) · **Applicant Roster** (group, rank,
screen) · **Manual Upload** (single-resume screening, original flow).

## 5. Inbox Ingestion (headless)
```bash
# Local .eml mailbox (offline; no Gmail account needed)
python scripts/fetch_inbox.py --source local --maildir tests/fixtures/mail

# Your Gmail MCP server (requires EMAIL_SOURCE=mcp settings in .env)
python scripts/fetch_inbox.py --source mcp --label Candidates --max-results 25
```
Options: `--label`, `--query`, `--max-results`, `--lookback-days`, `--db`.

## 6. Generate Demo Mailbox
```bash
python scripts/generate_sample_mailbox.py           # writes tests/fixtures/mail/*.eml
python scripts/generate_sample_mailbox.py some/dir  # or a custom directory
```

