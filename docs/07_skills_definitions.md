# Skills Definition File

### Skill: `skill_evaluate_github_repo_depth`
- **Goal:** Differentiate between fork-heavy/tutorial repositories and genuine software development.
- **Rules:**
  1. Reject single-commit boilerplate repositories as evidence of proficiency.
  2. Map top repository languages against the skills claimed in the parsed resume.
  3. Mark verification status as `UNVERIFIED_MANUAL_REVIEW` if the account is private or unreachable.

### Skill: `skill_generate_technical_probe_questions`
- **Goal:** Produce questions targeting specific knowledge gaps rather than generic trivia questions.
- **Rules:**
  1. Base questions strictly on claimed skills that lack verifiable repository implementations.
  2. Frame questions around production trade-offs, architecture decisions, and edge-case handling.
