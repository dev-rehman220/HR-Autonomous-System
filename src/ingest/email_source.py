"""Neutral email + attachment contracts shared by every ingestion source.

The Gmail MCP adapter, the local `.eml` adapter and any future source all speak
this small vocabulary, so the pipeline never depends on a specific provider.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

DEFAULT_MAX_RESULTS = 25
DEFAULT_LOOKBACK_DAYS = 30


class EmailSourceError(RuntimeError):
    """Raised when an email source cannot be reached, configured, or queried."""


@dataclass
class Attachment:
    filename: str
    content_type: str
    data: bytes

    @property
    def extension(self) -> str:
        if "." not in self.filename:
            return ""
        return f".{self.filename.rsplit('.', 1)[1].lower()}"


@dataclass
class EmailMessage:
    message_id: str
    sender: str = ""
    subject: str = ""
    date: str = ""
    body: str = ""
    attachments: list[Attachment] = field(default_factory=list)


@runtime_checkable
class EmailSource(Protocol):
    """Anything that can return candidate application emails for a filter."""

    def fetch(
        self,
        *,
        label: str = "",
        query: str = "",
        max_results: int = DEFAULT_MAX_RESULTS,
        lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    ) -> list[EmailMessage]:
        ...
