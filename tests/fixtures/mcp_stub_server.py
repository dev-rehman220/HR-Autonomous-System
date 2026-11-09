"""Minimal stdio MCP servers used by tests and the probe script.

Two profiles are available, selected with ``STUB_PROFILE``:

* unset / ``single`` — one ``search_emails(query, maxResults)`` tool returning a
  JSON payload with inline base64 attachments (the adapter's legacy contract).
* ``gmail-api`` — the three-step ``list_messages`` / ``get_message`` /
  ``get_attachment`` surface used by ``@shinzolabs/gmail-mcp``: IDs first,
  a full message per ID, then base64url attachment bytes.

Both profiles return the same synthetic candidate so the pipeline sees an
identical résumé, and neither needs network access or credentials.
"""
from __future__ import annotations

import base64
import json
import os

import anyio
import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

LIST_TOOL = "list_messages"
GET_TOOL = "get_message"
ATTACHMENT_TOOL = "get_attachment"

MESSAGE_ID = "stub-0001"
ATTACHMENT_ID = "stub-att-0001"
CV_FILENAME = "jane_stub_cv.pdf"

SEARCH_TOOL = types.Tool(
    name="search_emails",
    description="Search Gmail and return messages with attachments as base64.",
    inputSchema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Gmail search query"},
            "maxResults": {"type": "integer", "description": "Maximum messages"},
        },
        "required": ["query"],
    },
)

LIST_TOOL_SPEC = types.Tool(
    name=LIST_TOOL,
    description="List messages matching a Gmail query.",
    inputSchema={
        "type": "object",
        "properties": {
            "q": {"type": "string", "description": "Gmail search query"},
            "maxResults": {"type": "integer", "description": "1-500"},
        },
    },
)

GET_TOOL_SPEC = types.Tool(
    name=GET_TOOL,
    description="Get one message by ID, fully hydrated.",
    inputSchema={
        "type": "object",
        "properties": {"id": {"type": "string"}},
        "required": ["id"],
    },
)

ATTACHMENT_TOOL_SPEC = types.Tool(
    name=ATTACHMENT_TOOL,
    description="Get attachment bytes (base64url) for a message.",
    inputSchema={
        "type": "object",
        "properties": {
            "messageId": {"type": "string"},
            "id": {"type": "string"},
        },
        "required": ["messageId", "id"],
    },
)

CV_LINES = [
    "Jane Stub",
    "Senior Backend Engineer",
    "jane.stub@example.com | +1 555 0100",
    "8 years building Python services with FastAPI, PostgreSQL, Docker, Kubernetes.",
    "Led migration of a monolith to event-driven services on AWS.",
    "BSc Computer Science, 2016.",
]


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


def _pdf() -> bytes:
    return _build_pdf(CV_LINES)


def _payload() -> dict:
    return {
        "messages": [
            {
                "id": MESSAGE_ID,
                "from": "Jane Stub <jane.stub@example.com>",
                "subject": "Application: Senior Backend Engineer",
                "date": "2026-11-06T10:00:00Z",
                "body": "Hi, my CV is attached.",
                "attachments": [
                    {
                        "filename": CV_FILENAME,
                        "mime_type": "application/pdf",
                        "data_base64": base64.b64encode(_pdf()).decode(),
                    }
                ],
            }
        ]
    }


def _gmail_message() -> dict:
    """Shape returned by Shinzo's ``get_message`` after body decoding."""
    return {
        "id": MESSAGE_ID,
        "threadId": "stub-thread-0001",
        "snippet": "Hi, my CV is attached.",
        "internalDate": "1793959200000",
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": [
                {"name": "From", "value": "Jane Stub <jane.stub@example.com>"},
                {"name": "To", "value": "jobs@example.com"},
                {"name": "Subject", "value": "Application: Senior Backend Engineer"},
                {"name": "Date", "value": "Thu, 06 Nov 2026 10:00:00 +0000"},
            ],
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {"data": "Hi, my CV is attached.", "size": 25},
                },
                {
                    "mimeType": "application/pdf",
                    "filename": CV_FILENAME,
                    "body": {"attachmentId": ATTACHMENT_ID, "size": len(_pdf())},
                },
            ],
        },
    }


def _profile() -> str:
    return os.environ.get("STUB_PROFILE", "single").strip().lower()


def _tools() -> list[types.Tool]:
    if _profile() == "gmail-api":
        return [LIST_TOOL_SPEC, GET_TOOL_SPEC, ATTACHMENT_TOOL_SPEC]
    return [SEARCH_TOOL]


def _result(payload: dict) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(payload))]
    )


async def _list_tools(context, params):
    return types.ListToolsResult(tools=_tools())


def _call_search(arguments: dict) -> types.CallToolResult:
    query = str(arguments.get("query", ""))
    payload = {"messages": []} if "nothing" in query.lower() else _payload()
    return _result(payload)


def _call_list(arguments: dict) -> types.CallToolResult:
    query = str(arguments.get("q", ""))
    if "nothing" in query.lower():
        return _result({"messages": [], "resultSizeEstimate": 0})
    return _result(
        {
            "messages": [{"id": MESSAGE_ID, "threadId": "stub-thread-0001"}],
            "resultSizeEstimate": 1,
        }
    )


def _call_get(arguments: dict) -> types.CallToolResult:
    if str(arguments.get("id")) != MESSAGE_ID:
        return _result({"error": "Requested entity was not found."})
    return _result(_gmail_message())


def _call_attachment(arguments: dict) -> types.CallToolResult:
    if str(arguments.get("id")) != ATTACHMENT_ID:
        return _result({"error": "Attachment not found."})
    encoded = base64.urlsafe_b64encode(_pdf()).decode().rstrip("=")
    return _result({"data": encoded, "size": len(_pdf())})


_HANDLERS = {
    "search_emails": _call_search,
    LIST_TOOL: _call_list,
    GET_TOOL: _call_get,
    ATTACHMENT_TOOL: _call_attachment,
}


async def _call_tool(context, params):
    name = getattr(params, "name", "") or ""
    handler = _HANDLERS.get(name)
    if handler is None:
        return _result({"error": f"Unknown tool: {name}"})
    return handler(dict(getattr(params, "arguments", None) or {}))


server = Server("stub-gmail-mcp", on_list_tools=_list_tools, on_call_tool=_call_tool)


async def main() -> None:
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    anyio.run(main)
