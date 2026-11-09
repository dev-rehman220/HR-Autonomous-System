"""Ingestion tests: attachment extraction, sources, MCP payload mapping, pipeline."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest

from src.ingest.attachments import (
    AttachmentExtractionError,
    extract_text,
    is_cv_attachment,
    pick_cv_attachments,
)
from src.ingest.email_source import Attachment, EmailMessage
from src.ingest.gmail_mcp_source import build_gmail_query, messages_from_payload
from src.ingest.local_source import LocalFileSource
from src.ingest.pipeline import ingest
from src.roster.store import SqliteApplicantStore

FIXTURE_MAILBOX = Path(__file__).parent / "fixtures" / "mail"


# --------------------------------------------------------------------------- #
# Attachment extraction
# --------------------------------------------------------------------------- #
def test_extract_text_from_txt():
    assert "Jane" in extract_text("cv.txt", b"Jane Doe\nPython developer")


def test_extract_text_uses_content_type_without_filename_extension(monkeypatch):
    monkeypatch.setattr("src.ingest.attachments._extract_pdf", lambda data: "Jane Doe")
    assert extract_text("resume", b"pdf-bytes", "application/pdf; charset=binary") == "Jane Doe"


def test_extract_text_from_docx():
    docx = pytest.importorskip("docx")
    document = docx.Document()
    document.add_paragraph("Jane Doe")
    document.add_paragraph("Python, FastAPI, Docker")
    buffer = BytesIO()
    document.save(buffer)
    assert "Jane Doe" in extract_text("cv.docx", buffer.getvalue())


def test_extract_text_from_rtf():
    rtf = rb"{\rtf1\ansi\deff0 {\fonttbl {\f0 Times;}}\f0\fs24 Jane Doe\par Python developer}"
    assert "Jane Doe" in extract_text("cv.rtf", rtf)


def test_extract_text_rejects_unsupported_and_empty():
    with pytest.raises(AttachmentExtractionError):
        extract_text("cv.exe", b"MZ")
    with pytest.raises(AttachmentExtractionError):
        extract_text("cv.txt", b"")


def test_extract_text_rejects_corrupt_pdf():
    with pytest.raises(AttachmentExtractionError):
        extract_text("cv.pdf", b"definitely not a pdf")


def test_is_cv_attachment_by_extension_and_content_type():
    assert is_cv_attachment("resume.pdf")
    assert is_cv_attachment("x", "application/pdf")
    assert not is_cv_attachment("photo.png", "image/png")


def test_pick_cv_attachments_filters_non_cv():
    attachments = [
        Attachment("cv.pdf", "application/pdf", b"x"),
        Attachment("photo.png", "image/png", b"y"),
    ]
    picked = pick_cv_attachments(attachments)
    assert [item.filename for item in picked] == ["cv.pdf"]


# --------------------------------------------------------------------------- #
# Local source
# --------------------------------------------------------------------------- #
def test_local_source_reads_fixtures_and_respects_limit():
    source = LocalFileSource(FIXTURE_MAILBOX)
    assert len(source.fetch()) == 3
    assert len(source.fetch(max_results=1)) == 1


def test_local_source_missing_mailbox_raises():
    from src.ingest.email_source import EmailSourceError

    with pytest.raises(EmailSourceError):
        LocalFileSource(FIXTURE_MAILBOX / "does-not-exist").fetch()


# --------------------------------------------------------------------------- #
# Gmail MCP payload mapping (transport-agnostic, pure)
# --------------------------------------------------------------------------- #
def test_build_gmail_query_combines_label_query_and_window():
    assert build_gmail_query("Candidates", "has:attachment", 30) == (
        "label:Candidates has:attachment newer_than:30d"
    )
    assert build_gmail_query("", "", 0) == "has:attachment"


def test_messages_from_payload_decodes_attachments():
    import base64

    payload = {
        "messages": [
            {
                "id": "m1",
                "from": "Jane <jane@example.com>",
                "subject": "Application",
                "attachments": [
                    {
                        "filename": "cv.pdf",
                        "mime_type": "application/pdf",
                        "data_base64": base64.b64encode(b"%PDF-1.4 fake").decode(),
                    }
                ],
            }
        ]
    }
    messages = messages_from_payload(payload)
    assert len(messages) == 1
    assert messages[0].message_id == "m1"
    assert messages[0].attachments[0].data == b"%PDF-1.4 fake"
    assert messages[0].attachments[0].extension == ".pdf"


def test_messages_from_payload_accepts_list_and_skips_bad_attachments():
    messages = messages_from_payload([{"id": "m2", "attachments": [{"filename": "cv.pdf"}]}])
    assert len(messages) == 1
    assert messages[0].attachments == []


def test_build_email_source_local_reads_configured_mailbox():
    from src.ingest import build_email_source
    from src.ingest.local_source import LocalFileSource

    source = build_email_source("local")
    assert isinstance(source, LocalFileSource)
    assert str(FIXTURE_MAILBOX) in str(source.root)


def test_build_email_source_mcp_reads_configured_command(monkeypatch):
    from src.ingest import build_email_source
    from src.ingest import gmail_mcp_source
    from src.ingest.gmail_mcp_source import GmailMCPSource

    monkeypatch.setattr(gmail_mcp_source, "GMAIL_MCP_COMMAND", "npx -y fake-gmail-mcp")
    source = build_email_source("mcp")
    assert isinstance(source, GmailMCPSource)
    assert source.command == "npx -y fake-gmail-mcp"


def test_build_email_source_rejects_unknown_source():
    from src.ingest import build_email_source
    from src.ingest.email_source import EmailSourceError

    with pytest.raises(EmailSourceError):
        build_email_source("carrier-pigeon")


# --------------------------------------------------------------------------- #
# Pipeline
# --------------------------------------------------------------------------- #
def test_pipeline_ingests_new_applicants_then_dedups():
    store = SqliteApplicantStore(":memory:")
    source = LocalFileSource(FIXTURE_MAILBOX)

    first = ingest(source, store)
    assert first.fetched == 3
    assert first.new == 2
    assert first.skipped == 1
    assert store.count() == 2

    second = ingest(source, store)
    assert second.duplicates == 2
    assert second.new == 0
    assert store.count() == 2
    store.close()


def test_pipeline_assigns_specialization_and_email_fallback():
    store = SqliteApplicantStore(":memory:")
    ingest(LocalFileSource(FIXTURE_MAILBOX), store)

    by_name = {row["full_name"]: row for row in store.list()}
    assert by_name["Jane Doe"]["specialization"] == "Backend"
    assert by_name["Omar Ali"]["specialization"] == "ML/AI"
    assert by_name["Jane Doe"]["email"] == "jane.doe@example.com"
    store.close()


def test_pipeline_records_errors_for_unreadable_attachment():
    store = SqliteApplicantStore(":memory:")
    message = EmailMessage(
        message_id="bad-1",
        sender="Bad <bad@example.com>",
        subject="Application",
        attachments=[Attachment("cv.pdf", "application/pdf", b"not a real pdf")],
    )

    class _OneMessageSource:
        def fetch(self, **kwargs):
            return [message]

    result = ingest(_OneMessageSource(), store)
    assert result.new == 0
    assert result.skipped == 1
    assert result.errors
    store.close()


def test_pipeline_ingests_extensionless_cv_using_content_type(monkeypatch):
    monkeypatch.setattr(
        "src.ingest.pipeline.extract_text",
        lambda filename, data, content_type: "Jane Doe\nPython developer",
    )
    store = SqliteApplicantStore(":memory:")
    message = EmailMessage(
        message_id="mime-only",
        sender="Jane <jane@example.com>",
        subject="Application",
        attachments=[Attachment("resume", "text/plain", b"resume bytes")],
    )

    class _OneMessageSource:
        def fetch(self, **kwargs):
            return [message]

    result = ingest(_OneMessageSource(), store)
    assert result.new == 1
    assert result.errors == []
    store.close()


def test_screen_on_import_calls_the_screening_bridge(monkeypatch):
    from src.ingest import pipeline

    calls = []
    monkeypatch.setattr(pipeline, "SCREEN_ON_IMPORT", True)
    monkeypatch.setattr(
        "src.screening.screen_and_persist",
        lambda applicant, store: calls.append(applicant["id"]),
    )

    store = SqliteApplicantStore(":memory:")
    result = ingest(LocalFileSource(FIXTURE_MAILBOX), store)

    assert len(calls) == 2
    assert result.screened == 2
    assert "auto-screened" in result.summary
    store.close()


def test_screen_on_import_failure_does_not_abort_ingest(monkeypatch):
    from src.ingest import pipeline

    def boom(applicant, store):
        raise RuntimeError("provider down")

    monkeypatch.setattr(pipeline, "SCREEN_ON_IMPORT", True)
    monkeypatch.setattr("src.screening.screen_and_persist", boom)

    store = SqliteApplicantStore(":memory:")
    result = ingest(LocalFileSource(FIXTURE_MAILBOX), store)

    assert result.new == 2
    assert result.screened == 0
    assert len(result.errors) == 2
    store.close()
