# Evaluation Suite & Test Matrix

| Test ID | Scenario | Expected Flow | Success Criteria |
|---|---|---|---|
| `TC-01` | Valid resume with active GitHub username | Parser -> ChromaDB -> GitHub API -> Score >= 75 -> Draft Invite[cite: 1] | All tools execute; valid invitation email generated[cite: 1] |
| `TC-02` | Resume without GitHub username | Parser -> ChromaDB -> Skip GitHub -> Generate Fit Score with unverified tag[cite: 1] | Workflow completes cleanly without crashing[cite: 1] |
| `TC-03` | Candidate does not meet experience baseline | Parser -> ChromaDB -> Score < 60 -> Draft Rejection[cite: 1] | Respectful rejection generated; calendar slots omitted[cite: 1] |
| `TC-04` | Encrypted or corrupt PDF file | Parser fails gracefully | Returns clear error message and halts state machine safely |
