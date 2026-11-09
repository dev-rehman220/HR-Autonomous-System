# Guardrails, Safety Rules & Constraints

1. **PII Protection:** Phone numbers, home addresses, and private contact data must be scrubbed before passing text to external API tools.
2. **Bias Mitigation:** Age, graduation years, candidate photographs, and ethnic/gender indicators must not factor into candidate ranking or fit scoring.
3. **Human-in-the-Loop Requirement:** Outbound candidate communication must remain in draft state until reviewed and confirmed by a human user in the UI.
4. **Data Isolation:** Internal salary limits must remain confined to the recruiter dashboard and never leaked into candidate-facing draft emails.
