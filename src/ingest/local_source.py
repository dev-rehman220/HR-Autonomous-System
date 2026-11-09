"""Offline `.eml` mailbox source used for demos and deterministic tests.

`EMAIL_SOURCE=local` points the pipeline at a folder of `.eml` files (see
`tests/fixtures/mail/`), so the whole ingestion flow runs with no Gmail account.
"""
from __future__ import annotations

from email import policy
from email.message import Message
from email.parser import BytesParser
from pathlib import Path

from src.ingest.email_source import (
    DEFAULT_LOOKBACK_DAYS,
    DEFAULT_MAX_RESULTS,
    Attachment,
    EmailMessage,
    EmailSourceError,
)


class LocalFileSource:
    """Reads candidate emails from `*.eml` files in a directory."""

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def fetch(
        self,
        *,
        label: str = "",
        query: str = "",
        max_results: int = DEFAULT_MAX_RESULTS,
        lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    ) -> list[EmailMessage]:
        if not self.root.exists():
            raise EmailSourceError(f"Local mailbox not found: {self.root}")

        messages: list[EmailMessage] = []
        for path in sorted(self.root.glob("*.eml")):
            messages.append(_parse_eml(path))
            if len(messages) >= max_results:
                break
        return messages


def _parse_eml(path: Path) -> EmailMessage:
    message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
    body_parts: list[str] = []
    attachments: list[Attachment] = []

    for part in message.walk() if message.is_multipart() else [message]:
        if part.is_multipart():
            continue
        filename = part.get_filename()
        disposition = part.get_content_disposition()
        payload = _payload_bytes(part)
        if disposition == "attachment" or (filename and disposition != "inline"):
            attachments.append(
                Attachment(
                    filename=filename or "attachment.bin",
                    content_type=part.get_content_type(),
                    data=payload,
                )
            )
        elif part.get_content_type() == "text/plain":
            body_parts.append(payload.decode("utf-8", errors="replace"))

    return EmailMessage(
        message_id=message.get("Message-ID") or path.stem,
        sender=message.get("From", ""),
        subject=message.get("Subject", ""),
        date=message.get("Date", ""),
        body="\n".join(body_parts).strip(),
        attachments=attachments,
    )


def _payload_bytes(part: Message) -> bytes:
    payload = part.get_payload(decode=True)
    if isinstance(payload, bytes):
        return payload
    raw = part.get_payload()
    return raw.encode("utf-8", errors="replace") if isinstance(raw, str) else b""
