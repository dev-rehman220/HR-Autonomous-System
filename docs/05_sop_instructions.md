# Standard Operating Procedure (SOP) & Execution Logic

```text
[User Uploads PDF]
│
▼
[State: Ingest Resume] ──> Tool: Resume Parser
│
▼
[State: Role Alignment] ──> Tool: ChromaDB RAG (Query active JDs)
│
▼
[State: External Verification] ──> Tool: GitHub Profile Evaluator
│
▼
[State: Synthesize & Score] ──> Multi-factor scoring (Skills, Experience, Gap Analysis)
│
▼
[State: Question Formulation] ──> Generate tailored technical verification questions
│
▼
[State: Action Drafting] ──> Tool: Calendar/Scheduler ──> Draft invite or rejection
│
▼
[Human Review & Confirmation] (Streamlit UI)
```

## Execution Protocol
1. **Resume Processing:** Execute `parse_resume_pdf(file_path)` to extract raw text and contact details[cite: 1].
2. **Requisition Retrieval:** Perform semantic similarity search in ChromaDB to retrieve matching job requirements and salary bounds[cite: 1].
3. **Signal Verification:** If a GitHub username exists, execute `evaluate_github_profile(username)` to gather repository counts, languages, and commit history[cite: 1].
4. **Scoring:** Calculate a 0-100 fit score against core skills (40%), experience depth (30%), and verified code activity (30%).
5. **Interview Formulation:** Formulate 3 customized technical screening questions based on detected gaps[cite: 1].
6. **Next Step Drafting:** If score >= 70, fetch available recruiter calendar slots and draft an invitation email[cite: 1]; if score < 70, draft a rejection notice.
