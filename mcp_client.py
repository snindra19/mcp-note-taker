"""MCP client: starts a server over stdio, lists its tools and calls them.

Each public function starts the server, does one job and shuts it down. Each
returns (result, error message or None) and doesn't raise. Exception text is
never shown to the user, so a server failure can't leak details.

This file never reads the API key. Servers get only the MCP SDK's short list of
safe environment variables, so the key stays out of the fetch server entirely.
"""

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path
from typing import Awaitable, Callable

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

PROJECT_FOLDER = Path(__file__).resolve().parent
OVERALL_TIMEOUT_SECONDS = 20

# The arguments that start each server with this same Python interpreter.
SERVER_ARGUMENTS = {
    "weather": [str(PROJECT_FOLDER / "weather_server.py")],
    "fetch": ["-m", "mcp_server_fetch"],
}

# Messages from this client and the weather server carry a stable code, as in
# "MCP error [server_timeout]: ..." or "Weather error [city_not_found]: ...".
CODED_MESSAGE_PATTERN = re.compile(
    r"^(?:MCP error|Weather error|Weather notice) \[([a-z_]+)\]: (.*)$", re.DOTALL
)


def split_message_code(text: str) -> tuple[str | None, str]:
    """Return (code, plain message) for a coded message, or (None, text) otherwise."""
    match = CODED_MESSAGE_PATTERN.match(text)
    if match is None:
        return None, text
    return match.group(1), match.group(2)


def client_error(code: str, message: str) -> str:
    """Return a client failure message with its stable code."""
    return f"MCP error [{code}]: {message}"


async def run_on_server(
    server_name: str,
    action: Callable[[ClientSession], Awaitable[object]],
    progress: dict,
) -> object:
    """Start a server, run an action with its session, then shut the server down."""
    parameters = StdioServerParameters(
        command=sys.executable,
        args=SERVER_ARGUMENTS[server_name],
        cwd=str(PROJECT_FOLDER),
    )

    # Discard the server's stderr so its logs can't reach the user's output.
    with open(os.devnull, "w", encoding="utf-8") as discarded_output:
        async with stdio_client(parameters, errlog=discarded_output) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                progress["started"] = True
                return await action(session)


def run_with_timeout(
    server_name: str,
    action: Callable[[ClientSession], Awaitable[object]],
) -> tuple[object, str | None]:
    """Run an action on a server within the overall timeout; return (result, error)."""
    progress = {"started": False}
    try:
        operation = run_on_server(server_name, action, progress)
        result = asyncio.run(asyncio.wait_for(operation, OVERALL_TIMEOUT_SECONDS))
        return result, None
    except asyncio.TimeoutError:
        if progress["started"]:
            message = f"The {server_name} server did not answer within {OVERALL_TIMEOUT_SECONDS} seconds."
            return None, client_error("server_timeout", message)
        message = f"The {server_name} server did not start within {OVERALL_TIMEOUT_SECONDS} seconds."
        return None, client_error("server_start_timeout", message)
    except Exception:
        # Failures can arrive grouped from the SDK's task groups, so this is broad.
        if progress["started"]:
            return None, client_error("call_failed", f"The call to the {server_name} server failed.")
        return None, client_error("server_start_failed", f"Could not start the {server_name} server.")


def list_tools(server_name: str) -> tuple[list[dict] | None, str | None]:
    """Return each tool's name and description from a server, or an error."""

    async def read_tools(session: ClientSession) -> list[dict]:
        """Ask the server for its tools and keep the name and description."""
        response = await session.list_tools()

        # Copy the two fields used by the CLI from each tool.
        tools = []
        for tool in response.tools:
            tools.append({"name": tool.name, "description": tool.description or ""})
        return tools

    return run_with_timeout(server_name, read_tools)


def extract_text(result: object) -> str:
    """Join the text parts of a tool result."""
    text_parts = []

    # A result can hold several parts; only text parts are used.
    for part in result.content:
        if part.type == "text":
            text_parts.append(part.text)
    return "\n".join(text_parts)


def call_tool(server_name: str, tool_name: str, arguments: dict) -> tuple[str | None, str | None]:
    """Call a tool on a server and return (text result, error message or None)."""

    async def run_tool(session: ClientSession) -> object:
        """Call the tool with the session that was just opened."""
        return await session.call_tool(tool_name, arguments)

    result, error = run_with_timeout(server_name, run_tool)
    if error:
        return None, error

    text = extract_text(result)
    # A tool reports its own failures with is_error and a text explanation.
    if result.is_error:
        return None, text or f"The {server_name} server reported an error."
    return text, None


def print_all_tools() -> int:
    """Print the tools from both servers; return the process exit code."""
    exit_code = 0

    # Show each server's tools, carrying on if one of them fails.
    for server_name in SERVER_ARGUMENTS:
        print(f"{server_name} server:")
        tools, error = list_tools(server_name)
        if error:
            print(f"  {error}")
            exit_code = 1
            continue
        for tool in tools:
            first_line = tool["description"].strip().split("\n")[0]
            print(f"  {tool['name']}: {first_line}")
    return exit_code


def print_tool_result(server_name: str, tool_name: str, arguments: dict) -> int:
    """Call a tool, print the outcome and return the process exit code."""
    text, error = call_tool(server_name, tool_name, arguments)
    if error:
        print(error)
        return 1
    print(text)
    return 0


def main() -> int:
    """Run the command-line check of the server connections."""
    # Page text can contain characters the Windows console encoding lacks.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Check the MCP server connections.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("tools", help="list tools from both servers")
    weather_command = commands.add_parser("weather", help="get current weather for a city")
    weather_command.add_argument("city")
    fetch_command = commands.add_parser("fetch", help="fetch a URL")
    fetch_command.add_argument("url")
    options = parser.parse_args()

    if options.command == "tools":
        return print_all_tools()
    if options.command == "weather":
        return print_tool_result("weather", "get_current_weather", {"city": options.city})
    return print_tool_result("fetch", "fetch", {"url": options.url})


if __name__ == "__main__":
    sys.exit(main())
