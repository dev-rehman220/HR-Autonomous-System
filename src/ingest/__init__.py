"""Email ingestion: source abstraction, attachment extraction, and the pipeline."""
from src.config import EMAIL_SOURCE, LOCAL_MAILBOX_PATH
from src.ingest.email_source import (
    DEFAULT_LOOKBACK_DAYS,
    DEFAULT_MAX_RESULTS,
    Attachment,
    EmailMessage,
    EmailSource,
    EmailSourceError,
)
from src.ingest.pipeline import IngestResult, ingest

__all__ = [
    "Attachment",
    "EmailMessage",
    "EmailSource",
    "EmailSourceError",
    "IngestResult",
    "DEFAULT_MAX_RESULTS",
    "DEFAULT_LOOKBACK_DAYS",
    "build_email_source",
    "ingest",
]


def build_email_source(source: str | None = None) -> EmailSource:
    """Construct the configured EmailSource (``mcp`` or ``local``)."""
    resolved = (source or EMAIL_SOURCE).strip().lower()
    if resolved == "mcp":
        from src.ingest.gmail_mcp_source import GmailMCPSource

        return GmailMCPSource()
    if resolved == "local":
        from src.ingest.local_source import LocalFileSource

        return LocalFileSource(LOCAL_MAILBOX_PATH)
    raise EmailSourceError(f"Unknown EMAIL_SOURCE '{source or EMAIL_SOURCE}'")
