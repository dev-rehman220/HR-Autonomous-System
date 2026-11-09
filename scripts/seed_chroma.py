"""Seed the persistent ChromaDB vector store with active job requisitions (Phase 2).

Run from the project root:

    python scripts/seed_chroma.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow running as a plain script (adds the project root to sys.path).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import chromadb  # noqa: E402

from src.config import CHROMA_PATH, COLLECTION_NAME  # noqa: E402

# Metadata values must be scalars (str/int/float/bool) for ChromaDB, hence
# `required_skills` is stored as a comma-separated string.
JOB_DESCRIPTIONS: list[dict] = [
    {
        "id": "JOB-101",
        "title": "Senior Backend Engineer (Python/Cloud)",
        "text": (
            "Requires 4+ years of experience with Python, FastAPI, Docker, and PostgreSQL. "
            "Must have experience building distributed backend services, asynchronous queues, "
            "and cloud deployments on AWS/GCP."
        ),
        "metadata": {
            "job_id": "JOB-101",
            "role": "Senior Backend Engineer (Python/Cloud)",
            "required_skills": "Python, FastAPI, Docker, PostgreSQL, AWS, GCP",
            "min_experience_years": 4,
            "salary_bracket": "$140,000 - $175,000",
        },
    },
    {
        "id": "JOB-102",
        "title": "AI / Machine Learning Engineer",
        "text": (
            "Requires 3+ years of experience with Python, PyTorch, LangChain, RAG pipelines, and "
            "vector databases. Strong background in deploying LLM workflows and building "
            "multi-agent architectures."
        ),
        "metadata": {
            "job_id": "JOB-102",
            "role": "AI / Machine Learning Engineer",
            "required_skills": "Python, PyTorch, LangChain, RAG, LLM",
            "min_experience_years": 3,
            "salary_bracket": "$145,000 - $180,000",
        },
    },
    {
        "id": "JOB-103",
        "title": "Junior Full Stack Developer",
        "text": (
            "Requires 1+ years of experience with React, TypeScript, Python, and SQLite. "
            "Experience working with REST APIs, Git workflows, and front-end styling frameworks."
        ),
        "metadata": {
            "job_id": "JOB-103",
            "role": "Junior Full Stack Developer",
            "required_skills": "React, TypeScript, Python, SQLite, REST",
            "min_experience_years": 1,
            "salary_bracket": "$75,000 - $95,000",
        },
    },
]


def seed_database() -> int:
    """Upsert all requisitions into the persistent collection; return their count."""
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    collection = client.get_or_create_collection(name=COLLECTION_NAME)

    collection.upsert(
        ids=[job["id"] for job in JOB_DESCRIPTIONS],
        documents=[job["text"] for job in JOB_DESCRIPTIONS],
        metadatas=[job["metadata"] for job in JOB_DESCRIPTIONS],
    )

    print(
        f"Successfully seeded {len(JOB_DESCRIPTIONS)} job requisitions "
        f"into '{COLLECTION_NAME}' at {CHROMA_PATH}."
    )
    return len(JOB_DESCRIPTIONS)


if __name__ == "__main__":
    seed_database()
