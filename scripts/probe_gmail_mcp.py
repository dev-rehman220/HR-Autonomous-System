from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import (  # noqa: E402
    GMAIL_LABEL,
    GMAIL_LOOKBACK_DAYS,
    GMAIL_MAX_RESULTS,
    GMAIL_MCP_COMMAND,
    GMAIL_MCP_SEARCH_TOOL,
    GMAIL_MCP_TIMEOUT,
    GMAIL_MCP_URL,
    GMAIL_QUERY,
)
from src.ingest.email_source import EmailSourceError  # noqa: E402
from src.ingest.gmail_mcp_source import (  # noqa: E402
    GmailMCPSource,
    _first_text,
    _open_url_transport,
    _select_tool,
    build_gmail_query,
    messages_from_payload,
    split_mcp_command,
)


async def _inspect(session, source, query, max_results):
    await session.initialize()
    listing = await session.list_tools()
    tools = list(getattr(listing, "tools", []))
    print(f"TOOLS ({len(tools)}):")
    for tool in tools:
        schema = getattr(tool, "input_schema", None) or getattr(tool, "inputSchema", None)
        print(f"  - {tool.name}")
        print(f"    schema: {json.dumps(schema, default=str)}")

    names = [tool.name for tool in tools]
    selected = _select_tool(names, source.search_tool)
    print(f"SELECTED: {selected or 'NONE'}")
    if selected is None:
        print(f"No search-like tool found. Set GMAIL_MCP_SEARCH_TOOL to one of {names}")
        return 2
    if not query:
        return 0

    result = await session.call_tool(
        selected, arguments={"query": query, "maxResults": max_results}
    )
    text = _first_text(result) or ""
    print(f"RAW RESULT ({len(text)} chars, first 4000 shown):")
    print(text[:4000])

    try:
        payload = json.loads(text)
    except ValueError:
        print("PARSE: not JSON -> the tool returns prose and needs an adapter")
        return 3

    messages = messages_from_payload(payload)
    print(f"PARSE: {len(messages)} message(s)")
    for message in messages:
        attachments = [item.filename for item in message.attachments]
        print(
            f"  id={message.message_id} subject={message.subject!r} "
            f"attachments={attachments}"
        )
    if messages and not any(message.attachments for message in messages):
        print("WARNING: messages returned without attachments (IDs may need a second fetch)")
    return 0


async def _probe(source, query, max_results):
    if source.command:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        parts = split_mcp_command(source.command)
        params = StdioServerParameters(command=parts[0], args=parts[1:])
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                return await _inspect(session, source, query, max_results)

    from mcp import ClientSession

    async with _open_url_transport(source.url or "") as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            return await _inspect(session, source, query, max_results)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Diagnose a Gmail MCP server against the TalentAgent adapter contract."
    )
    parser.add_argument("--command", default=GMAIL_MCP_COMMAND)
    parser.add_argument("--url", default=GMAIL_MCP_URL)
    parser.add_argument("--tool", default=GMAIL_MCP_SEARCH_TOOL)
    parser.add_argument("--query", default="")
    parser.add_argument("--label", default=GMAIL_LABEL)
    parser.add_argument("--max-results", type=int, default=GMAIL_MAX_RESULTS)
    parser.add_argument("--lookback-days", type=int, default=GMAIL_LOOKBACK_DAYS)
    parser.add_argument("--timeout", type=int, default=GMAIL_MCP_TIMEOUT)
    parser.add_argument("--list-only", action="store_true")
    args = parser.parse_args()

    try:
        source = GmailMCPSource(
            command=args.command,
            url=args.url,
            search_tool=args.tool,
            timeout=args.timeout,
        )
    except EmailSourceError as exc:
        print(f"CONFIG ERROR: {exc}")
        return 1

    query = (
        ""
        if args.list_only
        else (args.query or build_gmail_query(args.label, GMAIL_QUERY, args.lookback_days))
    )

    try:
        return asyncio.run(
            asyncio.wait_for(_probe(source, query, args.max_results), timeout=args.timeout)
        )
    except EmailSourceError as exc:
        print(f"PROBE FAILED: {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001 - diagnostic tool reports everything
        print(f"PROBE FAILED: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
