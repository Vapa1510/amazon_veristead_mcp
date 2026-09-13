"""Veristead MCP server.

A verified smart-home execution layer for Alexa+: never claims a device
action succeeded without checking that it did (Capability Charter,
Pillar 1), and reports partial failures honestly instead of a blanket
"Okay" (Pillar 2).

Runs over Streamable HTTP (MCP spec 2025-11-25+), as required by the
Alexa+ track.  OAuth is provided by FastMCP's built-in GitHubProvider
when GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET, and OAUTH_BASE_URL are set
in the environment.  Without those variables the server starts in open
(unauthenticated) mode for local development.
"""
from __future__ import annotations

import os
import uvicorn
from starlette.middleware import Middleware
from starlette.types import ASGIApp, Receive, Scope, Send

from dotenv import load_dotenv
from fastmcp import FastMCP

from veristead.tools.devices import (
    execute_device_action_impl,
    get_device_status_impl,
    get_room_devices_impl,
    run_routine_impl,
    simulate_offline_device_impl,
)
from veristead.tools.memory import (
    forget_topic_impl,
    recall_context_impl,
    view_memory_impl,
)

load_dotenv()


def _build_auth():
    """Return a GitHubProvider auth object if credentials are configured,
    otherwise None (unauthenticated local-dev mode)."""
    client_id = os.getenv("GITHUB_CLIENT_ID")
    client_secret = os.getenv("GITHUB_CLIENT_SECRET")
    base_url = os.getenv("OAUTH_BASE_URL")

    if not (client_id and client_secret and base_url):
        return None

    from fastmcp.server.auth.providers.github import GitHubProvider

    return GitHubProvider(
        client_id=client_id,
        client_secret=client_secret,
        base_url=base_url,
        resource_base_url=base_url,
        issuer_url=base_url,
    )


_auth = _build_auth()
mcp = FastMCP("veristead", auth=_auth) if _auth else FastMCP("veristead")


@mcp.tool
def get_device_status(name_or_room: str | None = None) -> list[dict]:
    """Get current status for devices matching a name or room.

    Args:
        name_or_room: device name or room to filter by (substring match).
            Omit to get every device's status.
    """
    return get_device_status_impl(name_or_room)


@mcp.tool
def get_room_devices(room: str) -> list[dict]:
    """List every device in a room.

    Args:
        room: room name, e.g. "living room".
    """
    return get_room_devices_impl(room)


@mcp.tool
def execute_device_action(device: str, action: str) -> dict:
    """Execute an action on a device and verify it actually happened.

    Never reports success without re-reading the device's state after
    acting -- an offline or unresponsive device is reported as exactly
    that, not silently absorbed into a generic confirmation.

    Args:
        device: device name, e.g. "Kitchen Light".
        action: "on"/"off" for lights and plugs, "lock"/"unlock" for
            locks, "set:<temperature>" for the thermostat.
    """
    return execute_device_action_impl(device, action)


@mcp.tool
def run_routine(routine_name: str) -> dict:
    """Run a named multi-device routine (e.g. "good night", "good morning").

    Reports a consolidated result across every device touched, including
    any that failed or were offline -- never a blanket "done."

    Args:
        routine_name: the routine to run.
    """
    return run_routine_impl(routine_name)


@mcp.tool
def simulate_offline_device(device: str, offline: bool = True) -> dict:
    """Demo tool: mark a device offline (or back online) on command.

    Lets a demo deliberately trigger the partial-failure scenario instead
    of hoping it happens naturally.

    Args:
        device: device name.
        offline: True to take it offline, False to restore it.
    """
    return simulate_offline_device_impl(device, offline)


@mcp.tool
def recall_context(topic: str | None = None, limit: int = 10) -> list[dict]:
    """Recall recent household context, optionally filtered to one topic.

    Args:
        topic: optional topic to filter by (substring match).
        limit: max entries to return (1-50).
    """
    return recall_context_impl(topic, limit)


@mcp.tool
def view_memory() -> list[dict]:
    """Return everything currently stored in cross-session household memory."""
    return view_memory_impl()


@mcp.tool
def forget_topic(topic: str) -> dict:
    """Delete all remembered entries under a topic.

    Args:
        topic: the topic to forget (exact match, case-insensitive).
    """
    return forget_topic_impl(topic)


class StripWWWAuthenticateMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def wrapped_send(message):
            if message["type"] == "http.response.start" and message.get("status") == 401:
                message["headers"] = [
                    (k, v) for k, v in message.get("headers", []) if k.lower() != b"www-authenticate"
                ]
            await send(message)

        await self.app(scope, receive, wrapped_send)


def main() -> None:
    host = os.getenv("MCP_HOST", "0.0.0.0")
    port = int(os.getenv("MCP_PORT", "8000"))
    app = mcp.http_app(
        transport="streamable-http",
        middleware=[Middleware(StripWWWAuthenticateMiddleware)],
    )
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
