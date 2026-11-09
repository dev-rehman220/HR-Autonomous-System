"""Gmail ingestion via an external MCP server.

The adapter supports two transports, selected by configuration:

* **stdio** — spawn a command, e.g. ``GMAIL_MCP_COMMAND="npx -y <server>"``.
* **SSE / streamable HTTP** — connect to a running server, e.g.
  ``GMAIL_MCP_URL="http://localhost:3000/sse"``.

Expected MCP tool contract
--------------------------
The adapter calls the search tool (``GMAIL_MCP_SEARCH_TOOL``, default
``search_emails``) with ``{"query": "<gmail search>", "maxResults": <int>}`` and
expects a text result containing JSON of this shape::

    {
      "messages": [
        {
          "id": "18f...",
          "from": "Jane Doe <jane@example.com>",
          "subject": "Application: Backend Engineer",
          "date": "2026-10-01",
          "body": "Please find my CV attached.",
          "attachments": [
            {"filename": "jane_doe_cv.pdf",
             "mime_type": "application/pdf",
             "data_base64": "JVBERi0xLjQK..."}
          ]
        }
      ]
    }

Only ``filename`` and one of ``data_base64``/``content``/``data`` are required per
attachment. Adapt ``GMAIL_MCP_SEARCH_TOOL`` if your server names the tool
differently; the payload mapper itself is transport-agnostic.

Multi-step (Gmail API) servers
------------------------------
Servers that expose ``list_messages`` / ``get_message`` / ``get_attachment``
(e.g. ``@shinzolabs/gmail-mcp``) are detected automatically and driven through a
three-call flow instead: list matching IDs, hydrate each message, then fetch
each attachment by its ``attachmentId``. Message bodies arrive already decoded
as plain text; attachment bytes arrive as base64url.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import shlex
import shutil
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from src.config import (
    GMAIL_MCP_COMMAND,
    GMAIL_MCP_SEARCH_TOOL,
    GMAIL_MCP_TIMEOUT,
    GMAIL_MCP_URL,
)
from src.ingest.email_source import (
    DEFAULT_LOOKBACK_DAYS,
    DEFAULT_MAX_RESULTS,
    Attachment,
    EmailMessage,
    EmailSourceError,
)

logger = logging.getLogger(__name__)

_SEARCH_TOOL_HINTS = ("search", "list", "messages", "query", "fetch", "inbox")

# Tools that identify a Gmail-API-style server driven by list -> get -> attachment.
LIST_TOOL = "list_messages"
GET_TOOL = "get_message"
ATTACHMENT_TOOL = "get_attachment"
_GMAIL_API_TOOLS = (LIST_TOOL, GET_TOOL, ATTACHMENT_TOOL)


def build_gmail_query(label: str, query: str, lookback_days: int) -> str:
    parts: list[str] = []
    if label:
        parts.append(f"label:{label}")
    if query:
        parts.append(query)
    if lookback_days and lookback_days > 0:
        parts.append(f"newer_than:{int(lookback_days)}d")
    return " ".join(parts) or "has:attachment"


def messages_from_payload(payload: Any) -> list[EmailMessage]:
    """Map an MCP JSON payload onto neutral `EmailMessage` objects (pure)."""
    if isinstance(payload, dict):
        raw_messages = payload.get("messages") or payload.get("results") or []
    elif isinstance(payload, list):
        raw_messages = payload
    else:
        raw_messages = []

    messages: list[EmailMessage] = []
    for raw in raw_messages:
        if isinstance(raw, dict):
            messages.append(_message_from_dict(raw))
    return messages


def _message_from_dict(raw: dict) -> EmailMessage:
    attachments = [
        _attachment_from_dict(item)
        for item in (raw.get("attachments") or [])
        if isinstance(item, dict)
    ]
    return EmailMessage(
        message_id=str(raw.get("id") or raw.get("message_id") or raw.get("messageId") or uuid.uuid4().hex),
        sender=str(raw.get("from") or raw.get("sender") or raw.get("from_") or ""),
        subject=str(raw.get("subject") or ""),
        date=str(raw.get("date") or raw.get("internalDate") or ""),
        body=str(raw.get("body") or raw.get("snippet") or raw.get("text") or ""),
        attachments=[attachment for attachment in attachments if attachment is not None],
    )


def _attachment_from_dict(raw: dict) -> Optional[Attachment]:
    data = _decode_payload(raw)
    if data is None:
        return None
    return Attachment(
        filename=str(raw.get("filename") or raw.get("name") or "attachment.bin"),
        content_type=str(raw.get("mime_type") or raw.get("content_type") or raw.get("mimeType") or ""),
        data=data,
    )


def _decode_payload(raw: dict) -> Optional[bytes]:
    for key in ("data_base64", "content", "data", "base64"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return _b64decode(value)
    return None


def _b64decode(value: str) -> bytes:
    cleaned = "".join(value.split())
    try:
        return base64.b64decode(cleaned + "=" * (-len(cleaned) % 4))
    except Exception:  # noqa: BLE001 - fall back to raw text when not valid base64
        return value.encode("utf-8", errors="replace")


def _b64url_decode(value: str) -> bytes:
    """Decode Gmail's base64url payloads (``-``/``_`` alphabet, no padding)."""
    cleaned = "".join(value.split()).replace("-", "+").replace("_", "/")
    return base64.b64decode(cleaned + "=" * (-len(cleaned) % 4))


@dataclass
class AttachmentRef:
    """Pointer to an attachment that still needs a ``get_attachment`` call."""

    attachment_id: str
    filename: str
    mime_type: str


def parse_gmail_api_message(raw: dict) -> tuple[EmailMessage, list[AttachmentRef]]:
    """Map a ``users.messages.get`` payload onto ``EmailMessage`` + attachment refs.

    Pure: no I/O. Attachment bytes are returned separately because the Gmail API
    serves them from a different endpoint.
    """
    payload = raw.get("payload") if isinstance(raw, dict) else None
    if not isinstance(payload, dict):
        payload = {}
    headers = payload.get("headers") if isinstance(payload.get("headers"), list) else []
    refs: list[AttachmentRef] = []
    _collect_attachment_refs(payload, refs)
    return (
        EmailMessage(
            message_id=str(raw.get("id") or raw.get("messageId") or uuid.uuid4().hex),
            sender=_header(headers, "From"),
            subject=_header(headers, "Subject"),
            date=_header(headers, "Date")
            or _iso_from_internal_date(raw.get("internalDate")),
            body=_text_body(payload) or str(raw.get("snippet") or ""),
            attachments=[],
        ),
        refs,
    )


def _header(headers: list, name: str) -> str:
    wanted = name.lower()
    for item in headers:
        if not isinstance(item, dict):
            continue
        if str(item.get("name") or "").lower() == wanted:
            return str(item.get("value") or "")
    return ""


def _text_body(part: dict) -> str:
    if str(part.get("mimeType") or "").lower() == "text/plain":
        data = (part.get("body") or {}).get("data")
        if isinstance(data, str) and data.strip():
            return data
    for child in part.get("parts") or []:
        if isinstance(child, dict):
            found = _text_body(child)
            if found:
                return found
    return ""


def _collect_attachment_refs(part: dict, refs: list[AttachmentRef]) -> None:
    body = part.get("body") if isinstance(part.get("body"), dict) else {}
    filename = str(part.get("filename") or "")
    attachment_id = body.get("attachmentId")
    if filename and attachment_id:
        refs.append(
            AttachmentRef(
                attachment_id=str(attachment_id),
                filename=filename,
                mime_type=str(part.get("mimeType") or ""),
            )
        )
    for child in part.get("parts") or []:
        if isinstance(child, dict):
            _collect_attachment_refs(child, refs)


def _iso_from_internal_date(value: Any) -> str:
    try:
        millis = int(value)
    except (TypeError, ValueError):
        return ""
    return datetime.fromtimestamp(millis / 1000, tz=timezone.utc).isoformat()


def _json_payload(result, tool_name: str) -> dict:
    text = _first_text(result)
    if not text:
        raise EmailSourceError(f"MCP tool '{tool_name}' returned no text content.")
    try:
        payload = json.loads(text)
    except ValueError as exc:
        raise EmailSourceError(
            f"MCP tool '{tool_name}' did not return JSON: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise EmailSourceError(
            f"MCP tool '{tool_name}' returned unexpected JSON: {payload!r}"
        )
    return payload


class GmailMCPSource:
    """EmailSource backed by a Gmail MCP server (stdio command or URL)."""

    def __init__(
        self,
        command: Optional[str] = None,
        url: Optional[str] = None,
        search_tool: Optional[str] = None,
        timeout: Optional[int] = None,
    ):
        self.command = command if command is not None else GMAIL_MCP_COMMAND
        self.url = url if url is not None else GMAIL_MCP_URL
        self.search_tool = search_tool or GMAIL_MCP_SEARCH_TOOL
        self.timeout = timeout or GMAIL_MCP_TIMEOUT
        if not self.command and not self.url:
            raise EmailSourceError(
                "Gmail MCP is not configured: set GMAIL_MCP_COMMAND or GMAIL_MCP_URL."
            )

    def fetch(
        self,
        *,
        label: str = "",
        query: str = "",
        max_results: int = DEFAULT_MAX_RESULTS,
        lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    ) -> list[EmailMessage]:
        query_string = build_gmail_query(label, query, lookback_days)
        coro = self._collect(query_string, max_results)
        try:
            return _run_async(asyncio.wait_for(coro, timeout=self.timeout))
        except EmailSourceError:
            raise
        except Exception as exc:  # noqa: BLE001 - surface any transport error uniformly
            raise EmailSourceError(f"Gmail MCP fetch failed: {exc}") from exc

    async def _collect(self, query_string: str, max_results: int) -> list[EmailMessage]:
        if self.command:
            return await self._collect_stdio(query_string, max_results)
        return await self._collect_url(query_string, max_results)

    async def _collect_stdio(self, query_string: str, max_results: int) -> list[EmailMessage]:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        parts = split_mcp_command(self.command or "")
        if not parts:
            raise EmailSourceError("GMAIL_MCP_COMMAND is empty.")
        if os.sep in parts[0] and not os.path.exists(parts[0]):
            raise EmailSourceError(
                f"MCP command not found: {parts[0]!r}. If the path contains spaces, "
                "quote it inside GMAIL_MCP_COMMAND."
            )
        params = StdioServerParameters(command=parts[0], args=parts[1:])
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                return await self._query(session, query_string, max_results)

    async def _collect_url(self, query_string: str, max_results: int) -> list[EmailMessage]:
        from mcp import ClientSession

        async with _open_url_transport(self.url or "") as streams:
            read, write = streams[0], streams[1]
            async with ClientSession(read, write) as session:
                return await self._query(session, query_string, max_results)

    async def _query(self, session, query_string: str, max_results: int) -> list[EmailMessage]:
        await session.initialize()
        tools = await session.list_tools()
        names = [tool.name for tool in getattr(tools, "tools", [])]
        if all(name in names for name in _GMAIL_API_TOOLS):
            return await self._query_gmail_api(session, query_string, max_results)
        tool_name = _select_tool(names, self.search_tool)
        if tool_name is None:
            raise EmailSourceError(
                f"No Gmail search tool found among {names or '[]'}; "
                f"set GMAIL_MCP_SEARCH_TOOL (expected '{self.search_tool}')."
            )
        result = await session.call_tool(
            tool_name, arguments={"query": query_string, "maxResults": max_results}
        )
        text = _first_text(result)
        if not text:
            return []
        try:
            payload = json.loads(text)
        except ValueError as exc:
            raise EmailSourceError(f"MCP tool '{tool_name}' did not return JSON: {exc}") from exc
        return messages_from_payload(payload)

    async def _query_gmail_api(
        self, session, query_string: str, max_results: int
    ) -> list[EmailMessage]:
        """Drive a list -> get -> attachment server (e.g. @shinzolabs/gmail-mcp)."""
        listing = await session.call_tool(
            LIST_TOOL, arguments={"q": query_string, "maxResults": int(max_results)}
        )
        payload = _json_payload(listing, LIST_TOOL)
        if payload.get("error"):
            raise EmailSourceError(f"Gmail MCP '{LIST_TOOL}' failed: {payload['error']}")
        message_ids = [
            str(item.get("id"))
            for item in payload.get("messages") or []
            if isinstance(item, dict) and item.get("id")
        ][: int(max_results)]
        messages: list[EmailMessage] = []
        for message_id in message_ids:
            message = await self._hydrate_message(session, message_id)
            if message is not None:
                messages.append(message)
        return messages

    async def _hydrate_message(self, session, message_id: str) -> Optional[EmailMessage]:
        detail = await session.call_tool(GET_TOOL, arguments={"id": message_id})
        payload = _json_payload(detail, GET_TOOL)
        if payload.get("error"):
            logger.warning("Skipping message %s: %s", message_id, payload["error"])
            return None
        message, refs = parse_gmail_api_message(payload)
        for ref in refs:
            attachment = await self._fetch_attachment(session, message.message_id, ref)
            if attachment is not None:
                message.attachments.append(attachment)
        return message

    async def _fetch_attachment(
        self, session, message_id: str, ref: AttachmentRef
    ) -> Optional[Attachment]:
        result = await session.call_tool(
            ATTACHMENT_TOOL,
            arguments={"messageId": message_id, "id": ref.attachment_id},
        )
        payload = _json_payload(result, ATTACHMENT_TOOL)
        if payload.get("error"):
            logger.warning(
                "Skipping attachment %s on %s: %s",
                ref.filename,
                message_id,
                payload["error"],
            )
            return None
        data = payload.get("data")
        if not isinstance(data, str) or not data.strip():
            return None
        return Attachment(
            filename=ref.filename,
            content_type=ref.mime_type,
            data=_b64url_decode(data),
        )


def _select_tool(names: list[str], preferred: str) -> Optional[str]:
    if preferred in names:
        return preferred
    for name in names:
        lowered = name.lower()
        if any(hint in lowered for hint in _SEARCH_TOOL_HINTS):
            return name
    return None


def _first_text(result) -> Optional[str]:
    for item in getattr(result, "content", []) or []:
        text = getattr(item, "text", None)
        if text:
            return text
    return None


def split_mcp_command(command: str) -> list[str]:
    parts = shlex.split(command)
    if parts and not _executable_exists(parts[0]):
        resolved = _resolve_spaced_prefix(command)
        if resolved is not None:
            return resolved
    return parts


def _resolve_spaced_prefix(command: str) -> Optional[list[str]]:
    stripped = command.strip()
    for index, char in enumerate(stripped):
        if char != " ":
            continue
        executable = stripped[:index]
        if not _executable_exists(executable):
            continue
        remainder = stripped[index + 1 :].strip()
        if not remainder:
            return [executable]
        if os.path.isfile(remainder):
            return [executable, remainder]
        return [executable, *shlex.split(remainder)]
    return None


def _executable_exists(token: str) -> bool:
    if os.sep in token or token.startswith("."):
        return os.path.isfile(token) and os.access(token, os.X_OK)
    return shutil.which(token) is not None


def _open_url_transport(url: str):
    if url.rstrip("/").endswith("/sse"):
        from mcp.client.sse import sse_client

        return sse_client(url)
    try:
        from mcp.client.streamable_http import streamable_http_client
    except ImportError:
        from mcp.client.sse import sse_client

        return sse_client(url)
    return streamable_http_client(url)


def _run_async(coro):
    """Run a coroutine from sync code, even when an event loop is already running."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    box: dict = {}

    def runner() -> None:
        try:
            box["value"] = asyncio.run(coro)
        except BaseException as exc:  # noqa: BLE001 - re-raised in the caller thread
            box["error"] = exc

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join()
    if "error" in box:
        raise box["error"]
    return box.get("value")
