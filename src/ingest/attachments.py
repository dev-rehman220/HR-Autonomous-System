"""Extract plain text from candidate CV attachments (PDF, DOCX, TXT/MD, RTF)."""
from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader

from src.config import MAX_PDF_PAGES

CV_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".rtf"}
_TEXT_EXTENSIONS = {".txt", ".md"}
_PDF_CONTENT_TYPES = {"application/pdf"}
_DOCX_CONTENT_TYPES = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
}
_TEXT_CONTENT_TYPES = {"text/plain", "text/markdown"}


class AttachmentExtractionError(ValueError):
    """Raised when an attachment cannot be turned into usable text."""


def _extension(filename: str) -> str:
    if not filename or "." not in filename:
        return ""
    return f".{filename.rsplit('.', 1)[1].lower()}"


def is_cv_attachment(filename: str, content_type: str = "") -> bool:
    if _extension(filename) in CV_EXTENSIONS:
        return True
    content_type = (content_type or "").lower()
    if content_type in _PDF_CONTENT_TYPES | _DOCX_CONTENT_TYPES | _TEXT_CONTENT_TYPES:
        return True
    return content_type.startswith("text/")


def pick_cv_attachments(attachments: list) -> list:
    return [
        attachment
        for attachment in attachments or []
        if is_cv_attachment(attachment.filename, attachment.content_type)
    ]


def extract_text(filename: str, data: bytes, content_type: str = "") -> str:
    """Return the text of a CV attachment, dispatching on extension or MIME type."""
    if not data:
        raise AttachmentExtractionError(f"Empty attachment: {filename}")

    extension = _extension(filename)
    normalized_type = (content_type or "").split(";", 1)[0].strip().lower()
    try:
        if extension == ".pdf" or (not extension and normalized_type in _PDF_CONTENT_TYPES):
            text = _extract_pdf(data)
        elif extension == ".docx" or (not extension and normalized_type in _DOCX_CONTENT_TYPES):
            text = _extract_docx(data)
        elif extension in _TEXT_EXTENSIONS or (
            not extension and normalized_type in _TEXT_CONTENT_TYPES
        ):
            text = data.decode("utf-8", errors="replace")
        elif extension == ".rtf":
            text = _extract_rtf(data)
        else:
            raise AttachmentExtractionError(
                f"Unsupported attachment type '{extension or content_type or filename}'"
            )
    except AttachmentExtractionError:
        raise
    except Exception as exc:  # noqa: BLE001 - third-party readers raise many types
        raise AttachmentExtractionError(f"Could not read {filename}: {exc}") from exc

    if not text.strip():
        raise AttachmentExtractionError(f"No extractable text in {filename}")
    return text


def _extract_pdf(data: bytes) -> str:
    reader = PdfReader(BytesIO(data))
    if reader.is_encrypted and reader.decrypt("") == 0:
        raise AttachmentExtractionError("Encrypted PDF requires a password")
    pages = list(reader.pages)[:MAX_PDF_PAGES]
    return "\n".join(page.extract_text() or "" for page in pages)


def _extract_docx(data: bytes) -> str:
    try:
        import docx
    except ImportError as exc:  # pragma: no cover - dependency declared in requirements
        raise AttachmentExtractionError("python-docx is not installed") from exc

    document = docx.Document(BytesIO(data))
    parts = [paragraph.text for paragraph in document.paragraphs if paragraph.text]
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts)


def _extract_rtf(data: bytes) -> str:
    try:
        from striprtf.striprtf import rtf_to_text
    except ImportError as exc:  # pragma: no cover - dependency declared in requirements
        raise AttachmentExtractionError("striprtf is not installed") from exc

    return rtf_to_text(data.decode("utf-8", errors="replace"))
