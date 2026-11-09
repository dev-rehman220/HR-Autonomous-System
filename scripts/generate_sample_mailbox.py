"""Generate sample `.eml` application emails for offline demos and tests.

    python scripts/generate_sample_mailbox.py [output_dir]

Defaults to `tests/fixtures/mail/`. Each email carries a CV attachment that the
ingestion pipeline can parse, so `EMAIL_SOURCE=local` works with no Gmail account.
"""
from __future__ import annotations

import sys
from email.message import EmailMessage
from pathlib import Path

DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "mail"


def _build_pdf(lines: list[str]) -> bytes:
    def escape(value: str) -> str:
        return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    ops = ["BT", "/F1 12 Tf", "72 720 Td", "14 TL"]
    for line in lines:
        ops.append(f"({escape(line)}) Tj")
        ops.append("T*")
    ops.append("ET")
    stream = "\n".join(ops).encode("latin-1")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += str(index).encode() + b" 0 obj\n" + obj + b"\nendobj\n"

    xref_pos = len(out)
    out += b"xref\n0 " + str(len(objects) + 1).encode() + b"\n"
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += b"trailer\n<< /Size " + str(len(objects) + 1).encode() + b" /Root 1 0 R >>\n"
    out += b"startxref\n" + str(xref_pos).encode() + b"\n%%EOF"
    return bytes(out)


def _email(subject: str, sender: str, body: str, attachment: tuple[str, str, bytes] | None):
    message = EmailMessage()
    message["From"] = sender
    message["To"] = "hiring@ourteam.example"
    message["Subject"] = subject
    message["Message-ID"] = f"<{abs(hash(subject)) & 0xFFFFFFFF:x}@mail.example>"
    message.set_content(body)
    if attachment is not None:
        filename, mime_type, data = attachment
        maintype, _, subtype = mime_type.partition("/")
        message.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)
    return message


SAMPLES = [
    (
        "001_jane_doe.eml",
        _email(
            "Application: Senior Backend Engineer",
            "Jane Doe <jane.doe@example.com>",
            "Hi, please find my CV attached. I have 6 years building Python services.",
            (
                "jane_doe_cv.pdf",
                "application/pdf",
                _build_pdf(
                    [
                        "JANE DOE",
                        "jane.doe@example.com | +1 (555) 123-4567",
                        "github.com/janedoe",
                        "SUMMARY",
                        "Backend engineer with 6 years of experience building Python services.",
                        "SKILLS",
                        "Python, FastAPI, Docker, PostgreSQL, AWS, Kubernetes, Redis",
                    ]
                ),
            ),
        ),
    ),
    (
        "002_omar_ali.eml",
        _email(
            "Job application - ML Engineer",
            "Omar Ali <omar.ali@example.com>",
            "Attached is my resume for the ML Engineer role.",
            (
                "omar_ali_cv.txt",
                "text/plain",
                b"OMAR ALI\nomar.ali@example.com\ngithub.com/omarali\n\n"
                b"Machine learning engineer, 4 years experience. "
                b"Skills: Python, PyTorch, LangChain, RAG, LLM, Docker.",
            ),
        ),
    ),
    (
        "003_newsletter.eml",
        _email(
            "Weekly tech newsletter",
            "Newsletter <news@example.com>",
            "This email has no CV attachment and should be skipped by ingestion.",
            None,
        ),
    ),
]


def main() -> None:
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTPUT
    output.mkdir(parents=True, exist_ok=True)
    for filename, message in SAMPLES:
        (output / filename).write_bytes(message.as_bytes())
        print(f"wrote {output / filename}")


if __name__ == "__main__":
    main()
