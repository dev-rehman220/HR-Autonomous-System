"""Canonical specialization taxonomy and the skill/keyword rules behind it.

Applicants are grouped into these buckets and then ranked within each bucket.
The default list can be overridden with the ``TAXONOMY`` env var
(comma-separated), e.g. ``TAXONOMY=Backend,ML/AI,Mobile,Other``.
"""
from __future__ import annotations

from src.config import TAXONOMY_OVERRIDE

DEFAULT_SPECIALIZATIONS: list[str] = [
    "Backend",
    "Frontend",
    "Full-Stack",
    "ML/AI",
    "Data",
    "DevOps/Cloud",
    "Mobile",
    "QA",
    "Security",
    "Other",
]

SKILL_SPECIALIZATION: dict[str, str] = {
    # Backend
    "Python": "Backend", "FastAPI": "Backend", "Django": "Backend", "Flask": "Backend",
    "Go": "Backend", "Rust": "Backend", "Java": "Backend", "Node.js": "Backend",
    "PostgreSQL": "Backend", "MySQL": "Backend", "SQLite": "Backend",
    "MongoDB": "Backend", "Redis": "Backend", "Kafka": "Backend",
    "GraphQL": "Backend", "REST": "Backend", "gRPC": "Backend", "Spring Boot": "Backend",
    # Frontend
    "React": "Frontend", "TypeScript": "Frontend", "JavaScript": "Frontend",
    "Vue": "Frontend", "Angular": "Frontend", "Next.js": "Frontend", "Tailwind": "Frontend",
    # ML / AI
    "LangChain": "ML/AI", "LangGraph": "ML/AI", "PyTorch": "ML/AI",
    "TensorFlow": "ML/AI", "scikit-learn": "ML/AI", "RAG": "ML/AI", "LLM": "ML/AI",
    "Transformers": "ML/AI", "NLP": "ML/AI", "Computer Vision": "ML/AI",
    # Data
    "Airflow": "Data", "Spark": "Data", "dbt": "Data", "Snowflake": "Data",
    "Pandas": "Data", "ETL": "Data", "Hadoop": "Data",
    # DevOps / Cloud
    "Docker": "DevOps/Cloud", "Kubernetes": "DevOps/Cloud", "AWS": "DevOps/Cloud",
    "GCP": "DevOps/Cloud", "Azure": "DevOps/Cloud", "CI/CD": "DevOps/Cloud",
    "Terraform": "DevOps/Cloud", "Ansible": "DevOps/Cloud", "Git": "DevOps/Cloud",
    # Mobile
    "React Native": "Mobile", "Flutter": "Mobile", "Swift": "Mobile",
    "Kotlin": "Mobile", "Android": "Mobile", "iOS": "Mobile",
    # QA
    "Selenium": "QA", "Cypress": "QA", "Playwright": "QA", "pytest": "QA", "JUnit": "QA",
    # Security
    "OWASP": "Security", "Pentesting": "Security", "Cryptography": "Security",
}

KEYWORD_SPECIALIZATION: list[tuple[str, str]] = [
    ("machine learning", "ML/AI"), ("deep learning", "ML/AI"), ("data scientist", "ML/AI"),
    ("data engineer", "Data"), ("data pipeline", "Data"),
    ("devops", "DevOps/Cloud"), ("site reliability", "DevOps/Cloud"), ("platform engineer", "DevOps/Cloud"),
    ("frontend", "Frontend"), ("front-end", "Frontend"), ("full stack", "Full-Stack"), ("fullstack", "Full-Stack"),
    ("backend", "Backend"), ("back-end", "Backend"),
    ("android", "Mobile"), ("ios developer", "Mobile"), ("mobile engineer", "Mobile"),
    ("quality assurance", "QA"), ("test engineer", "QA"),
    ("security engineer", "Security"), ("penetration", "Security"),
]


def get_specializations() -> list[str]:
    if not TAXONOMY_OVERRIDE:
        return list(DEFAULT_SPECIALIZATIONS)
    custom = [item.strip() for item in TAXONOMY_OVERRIDE.split(",") if item.strip()]
    if "Other" not in custom:
        custom.append("Other")
    return custom


def specialization_scores(skills: list[str]) -> dict[str, int]:
    scores = {name: 0 for name in get_specializations()}
    normalized = {skill.strip().lower() for skill in skills or []}
    for skill, bucket in SKILL_SPECIALIZATION.items():
        if skill.lower() in normalized and bucket in scores:
            scores[bucket] += 1
    frontend, backend = scores.get("Frontend", 0), scores.get("Backend", 0)
    if frontend and backend and "Full-Stack" in scores:
        scores["Full-Stack"] = frontend + backend
    return scores


def classify_specialization(scores: dict[str, int]) -> tuple[str, float]:
    order = get_specializations()
    best = max(order, key=lambda name: (scores.get(name, 0), -order.index(name)))
    best_score = scores.get(best, 0)
    if best_score == 0:
        return "Other", 0.0
    total = sum(scores.values()) or 1
    return best, round(min(1.0, best_score / total), 2)


def keyword_specialization(text: str) -> tuple[str, float]:
    lowered = (text or "").lower()
    for keyword, bucket in KEYWORD_SPECIALIZATION:
        if keyword in lowered:
            return bucket, 0.3
    return "Other", 0.0
