# Tool & API Schema Specifications

### 1. Resume Parser Tool
- **Function:** `parse_resume(file_bytes: bytes) -> dict`[cite: 1]
- **Output:**
```json
{
  "full_name": "string",
  "email": "string",
  "github_username": "string | null",
  "skills": ["string"],
  "experience_years": "float",
  "raw_text": "string"
}
```

### 2. ChromaDB RAG Requisition Tool
- **Function:** `query_requisition_kb(query_text: str, n_results: int = 1) -> dict`
- **Output:**
```json
{
  "job_id": "string",
  "title": "string",
  "required_skills": ["string"],
  "min_experience_years": "integer",
  "salary_bracket": "string"
}
```

### 3. GitHub Profile Evaluator Tool
- **Function:** `evaluate_github_profile(username: str) -> dict`
- **Output:**
```json
{
  "user_exists": "boolean",
  "public_repos": "integer",
  "primary_languages": ["string"],
  "pinned_projects": [{"name": "string", "stars": "integer"}],
  "recent_commit_activity": "boolean"
}
```

### 4. Recruiter Schedule Tool
- **Function:** `fetch_recruiter_schedule(recruiter_id: str) -> dict`
- **Output:**
```json
{
  "available_slots": [
    {"datetime_iso": "string", "slot_id": "string"}
  ]
}
```
