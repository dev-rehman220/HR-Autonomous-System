# Problem Definition & Scope Document

## 1. Problem Statement
Technical recruiting teams face high volumes of candidate submissions, leading to slow turnaround times, shallow verification of technical credentials, and non-standardized evaluation rubrics. Manual screening is slow, inconsistent, and often misses deep alignment with team-specific technical benchmarks.

## 2. In-Scope Boundaries
- Parsing structured text and metadata from PDF resumes[cite: 1].
- Retrieving relevant Job Descriptions (JDs), core qualification criteria, and salary bands from an internal vector store (ChromaDB)[cite: 1].
- Inspecting candidate public profiles (GitHub API) to verify code contributions, primary languages, and repository quality[cite: 1].
- Generating a multi-dimensional fit score (Skills, Experience, Technical Depth).
- Formulating custom technical screening questions targeting identified resume gaps[cite: 1].
- Checking mock recruiter schedule availability and generating formatted draft interview invites or rejection notices[cite: 1].
- Interactive UI for recruiters to review, modify, and confirm decisions[cite: 1].

## 3. Out-of-Scope (Explicit Non-Goals)
- Live interviewing or automated voice/video assessment.
- Automatic dispatch of unreviewed candidate rejections or offers (human-in-the-loop required).
- Processing non-technical roles without an established technical rubric.
- Full ATS (Applicant Tracking System) lifecycle management (payroll, benefits onboarding).
