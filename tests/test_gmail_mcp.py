"""Gmail MCP source tests: tool selection, session query, transport error mapping."""
from __future__ import annotations

import asyncio
import base64
import json
import os
import shlex
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.ingest.email_source import EmailMessage, EmailSourceError
from src.ingest.gmail_mcp_source import (
    ATTACHMENT_TOOL,
    GET_TOOL,
    LIST_TOOL,
    GmailMCPSource,
    _b64url_decode,
    _first_text,
    _run_async,
    _select_tool,
    parse_gmail_api_message,
    split_mcp_command,
)


# --------------------------------------------------------------------------- #
# Tool selection & result extraction
# --------------------------------------------------------------------------- #
def test_select_tool_prefers_the_configured_name():
    assert _select_tool(["search_emails", "get_thread"], "search_emails") == "search_emails"


def test_select_tool_falls_back_to_a_search_like_hint():
    assert _select_tool(["gmail_search_messages", "delete_mail"], "search_emails") == (
        "gmail_search_messages"
    )
    assert _select_tool(["send_mail"], "search_emails") is None
    assert _select_tool([], "search_emails") is None


def test_first_text_reads_the_first_non_empty_content_block():
    assert _first_text(SimpleNamespace(content=[SimpleNamespace(text=""), SimpleNamespace(text="{}")])) == "{}"
    assert _first_text(SimpleNamespace(content=[])) is None
    assert _first_text(SimpleNamespace()) is None


# --------------------------------------------------------------------------- #
# Command splitting (paths containing spaces)
# --------------------------------------------------------------------------- #
def test_split_mcp_command_keeps_quoted_paths():
    command = "'/opt/my app/python' '/opt/my app/server.py' --flag"
    assert split_mcp_command(command) == [
        "/opt/my app/python",
        "/opt/my app/server.py",
        "--flag",
    ]


def test_split_mcp_command_resolves_an_unquoted_path_with_spaces(tmp_path):
    binary = tmp_path / "New Volume" / "python"
    binary.parent.mkdir()
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    script = tmp_path / "New Volume" / "server.py"
    script.write_text("")
    assert split_mcp_command(f"{binary} {script}") == [str(binary), str(script)]


def test_split_mcp_command_leaves_plain_commands_alone():
    assert split_mcp_command("npx -y @artymclabin/gmail-mcp") == [
        "npx",
        "-y",
        "@artymclabin/gmail-mcp",
    ]


# --------------------------------------------------------------------------- #
# Configuration errors
# --------------------------------------------------------------------------- #
def test_source_requires_command_or_url():
    with pytest.raises(EmailSourceError):
        GmailMCPSource(command="", url="")


def test_fetch_maps_transport_failure_to_email_source_error():
    class _Broken(GmailMCPSource):
        async def _collect(self, query_string, max_results):
            raise RuntimeError("connection refused")

    with pytest.raises(EmailSourceError) as excinfo:
        _Broken(command="true").fetch(label="Candidates")
    assert "Gmail MCP fetch failed" in str(excinfo.value)


def test_fetch_returns_collected_messages_and_builds_the_query(monkeypatch):
    seen = {}

    class _Stub(GmailMCPSource):
        async def _collect(self, query_string, max_results):
            seen["query"], seen["max_results"] = query_string, max_results
            return [EmailMessage(message_id="m1", sender="a@example.com", subject="CV")]

    result = _Stub(command="true").fetch(
        label="Candidates", query="has:attachment", max_results=10, lookback_days=7
    )
    assert [message.subject for message in result] == ["CV"]
    assert seen["query"] == "label:Candidates has:attachment newer_than:7d"
    assert seen["max_results"] == 10


# --------------------------------------------------------------------------- #
# Session query protocol
# --------------------------------------------------------------------------- #
class _FakeSession:
    def __init__(self, tool_names, payload_text):
        self.tool_names = tool_names
        self.payload_text = payload_text
        self.called = None
        self.initialized = False

    async def initialize(self):
        self.initialized = True

    async def list_tools(self):
        return SimpleNamespace(
            tools=[SimpleNamespace(name=name) for name in self.tool_names]
        )

    async def call_tool(self, name, arguments):
        self.called = (name, arguments)
        return SimpleNamespace(content=[SimpleNamespace(text=self.payload_text)])


def _query(source, session, query="label:Candidates", max_results=5):
    return asyncio.run(source._query(session, query, max_results))


def test_query_calls_the_search_tool_with_the_built_query():
    session = _FakeSession(["search_emails"], json.dumps({"messages": [{"id": "m1"}]}))
    source = GmailMCPSource(command="true")

    messages = _query(source, session)

    assert session.initialized is True
    assert session.called == (
        "search_emails",
        {"query": "label:Candidates", "maxResults": 5},
    )
    assert [message.message_id for message in messages] == ["m1"]


def test_query_raises_when_no_search_tool_is_exposed():
    session = _FakeSession(["send_mail"], "{}")
    with pytest.raises(EmailSourceError) as excinfo:
        _query(GmailMCPSource(command="true"), session)
    assert "GMAIL_MCP_SEARCH_TOOL" in str(excinfo.value)


def test_query_raises_when_the_tool_returns_non_json():
    session = _FakeSession(["search_emails"], "not json at all")
    with pytest.raises(EmailSourceError) as excinfo:
        _query(GmailMCPSource(command="true"), session)
    assert "did not return JSON" in str(excinfo.value)


def test_query_returns_empty_list_for_an_empty_result():
    session = _FakeSession(["search_emails"], "")
    assert _query(GmailMCPSource(command="true"), session) == []


# --------------------------------------------------------------------------- #
# Async bridge
# --------------------------------------------------------------------------- #
def test_run_async_executes_without_a_running_loop():
    async def produce():
        return 42

    assert _run_async(produce()) == 42


def test_run_async_works_inside_a_running_loop():
    async def inside_loop():
        async def produce():
            return "ok"

        return await asyncio.to_thread(_run_async, produce())

    assert asyncio.run(inside_loop()) == "ok"


def test_run_async_propagates_failures_from_inside_a_loop():
    async def inside_loop():
        async def boom():
            raise ValueError("kaboom")

        return await asyncio.to_thread(_run_async, boom())

    with pytest.raises(ValueError):
        asyncio.run(inside_loop())


# --------------------------------------------------------------------------- #
# Gmail API (list -> get -> attachment) servers
# --------------------------------------------------------------------------- #
def _gmail_api_message(**overrides):
    payload = {
        "id": "m-1",
        "snippet": "snippet fallback",
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": [
                {"name": "From", "value": "Jane <jane@example.com>"},
                {"name": "Subject", "value": "Application"},
                {"name": "Date", "value": "Thu, 06 Nov 2026 10:00:00 +0000"},
            ],
            "parts": [
                {"mimeType": "text/plain", "body": {"data": "Hello there"}},
                {
                    "mimeType": "application/pdf",
                    "filename": "cv.pdf",
                    "body": {"attachmentId": "att-1", "size": 5},
                },
            ],
        },
    }
    payload.update(overrides)
    return payload


def test_parse_gmail_api_message_maps_headers_body_and_attachment_refs():
    message, refs = parse_gmail_api_message(_gmail_api_message())

    assert message.message_id == "m-1"
    assert message.sender == "Jane <jane@example.com>"
    assert message.subject == "Application"
    assert message.date == "Thu, 06 Nov 2026 10:00:00 +0000"
    assert message.body == "Hello there"
    assert message.attachments == []
    assert [(ref.attachment_id, ref.filename, ref.mime_type) for ref in refs] == [
        ("att-1", "cv.pdf", "application/pdf")
    ]


def test_parse_gmail_api_message_falls_back_to_internal_date_and_snippet():
    raw = _gmail_api_message(internalDate="0")
    raw["payload"] = {"mimeType": "multipart/mixed", "headers": []}

    message, refs = parse_gmail_api_message(raw)

    assert message.sender == ""
    assert message.body == "snippet fallback"
    assert message.date == "1970-01-01T00:00:00+00:00"
    assert refs == []


def test_b64url_decode_handles_urlsafe_alphabet_without_padding():
    raw = b"\xfb\xff\xfe"
    encoded = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    assert "-" in encoded or "_" in encoded
    assert _b64url_decode(encoded) == raw


class _ScriptedSession:
    def __init__(self, handlers, tool_names=None):
        self.handlers = handlers
        self.tool_names = tool_names or [LIST_TOOL, GET_TOOL, ATTACHMENT_TOOL]
        self.calls = []
        self.initialized = False

    async def initialize(self):
        self.initialized = True

    async def list_tools(self):
        return SimpleNamespace(
            tools=[SimpleNamespace(name=name) for name in self.tool_names]
        )

    async def call_tool(self, name, arguments):
        self.calls.append((name, dict(arguments)))
        return SimpleNamespace(content=[SimpleNamespace(text=self.handlers[name](arguments))])


def test_query_drives_the_gmail_api_flow():
    def list_handler(arguments):
        assert arguments == {"q": "label:Candidates", "maxResults": 5}
        return json.dumps({"messages": [{"id": "m-1"}]})

    def get_handler(arguments):
        assert arguments == {"id": "m-1"}
        return json.dumps(_gmail_api_message())

    def attachment_handler(arguments):
        assert arguments == {"messageId": "m-1", "id": "att-1"}
        return json.dumps({"data": "JVBERi0=", "size": 5})

    session = _ScriptedSession(
        {
            LIST_TOOL: list_handler,
            GET_TOOL: get_handler,
            ATTACHMENT_TOOL: attachment_handler,
        }
    )

    messages = _query(GmailMCPSource(command="true"), session)

    assert session.initialized is True
    assert [name for name, _ in session.calls] == [LIST_TOOL, GET_TOOL, ATTACHMENT_TOOL]
    assert len(messages) == 1
    assert messages[0].attachments[0].filename == "cv.pdf"
    assert messages[0].attachments[0].data == b"%PDF-"


def test_query_skips_messages_and_attachments_that_error():
    session = _ScriptedSession(
        {
            LIST_TOOL: lambda arguments: json.dumps(
                {"messages": [{"id": "bad"}, {"id": "m-1"}]}
            ),
            GET_TOOL: lambda arguments: json.dumps(
                {"error": "gone"}
                if arguments["id"] == "bad"
                else _gmail_api_message()
            ),
            ATTACHMENT_TOOL: lambda arguments: json.dumps({"error": "nope"}),
        }
    )

    messages = _query(GmailMCPSource(command="true"), session)

    assert [message.message_id for message in messages] == ["m-1"]
    assert messages[0].attachments == []


def test_query_raises_when_list_messages_errors():
    session = _ScriptedSession({LIST_TOOL: lambda arguments: json.dumps({"error": "auth"})})

    with pytest.raises(EmailSourceError) as excinfo:
        _query(GmailMCPSource(command="true"), session)

    assert "list_messages" in str(excinfo.value)


def test_gmail_api_flow_end_to_end_over_stdio(monkeypatch):
    monkeypatch.setenv("STUB_PROFILE", "gmail-api")
    stub = Path(__file__).parent / "fixtures" / "mcp_stub_server.py"
    command = shlex.join([os.path.abspath(sys.executable), str(stub)])

    messages = GmailMCPSource(command=command, timeout=60).fetch(
        query="has:attachment", max_results=5
    )

    assert len(messages) == 1
    assert messages[0].message_id == "stub-0001"
    assert messages[0].subject == "Application: Senior Backend Engineer"
    assert messages[0].attachments[0].filename == "jane_stub_cv.pdf"
    assert messages[0].attachments[0].data.startswith(b"%PDF")
