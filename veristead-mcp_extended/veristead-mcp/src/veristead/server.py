"""Veristead MCP server.

A verified smart-home execution layer for Alexa+: never claims a device
action succeeded without checking that it did (Capability Charter,
Pillar 1), and reports partial failures honestly instead of a blanket
"Okay" (Pillar 2).

Runs over Streamable HTTP (MCP spec 2025-11-25+), as required by the
Alexa+ track. Auth (OAuth 2.1 + PKCE) and the Bedrock ambiguous-intent
layer are added in later phases -- see the project roadmap.
"""
from __future__ import annotations

import os

import uvicorn
from dotenv import load_dotenv
from fastmcp import FastMCP
from starlette.middleware import Middleware
from starlette.types import ASGIApp, Receive, Scope, Send

from veristead.tools.devices import (
    execute_device_action_impl,
    get_device_status_impl,
    get_room_devices_impl,
    run_routine_impl,
    simulate_offline_device_impl,
)
from veristead.tools.intent import interpret_command_impl
from veristead.tools.memory import (
    forget_topic_impl,
    recall_context_impl,
    view_memory_impl,
)

load_dotenv()


class StripWWWAuthenticateMiddleware:
    """Strip the WWW-Authenticate header from 401 responses.

    FastMCP's built-in OAuth middleware adds this header by default (RFC
    6750 behavior). Alexa+'s MCP integration spec specifically requires
    it be ABSENT on 401 responses. FastMCP exposes no config flag for
    this, so it's removed here at the ASGI layer instead of patching
    FastMCP's internals directly -- keeps this working across FastMCP
    version upgrades.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def wrapped_send(message: dict) -> None:
            if message["type"] == "http.response.start" and message["status"] == 401:
                message["headers"] = [
                    (k, v) for k, v in message["headers"] if k.lower() != b"www-authenticate"
                ]
            await send(message)

        await self.app(scope, receive, wrapped_send)


def _build_auth():
    """Build the GitHub OAuth provider if credentials are configured.

    Returns None (no auth) when GITHUB_CLIENT_ID/SECRET aren't set, so
    local dev and MCP Inspector testing keep working unauthenticated.
    Set both env vars to run the server in secured mode.
    """
    client_id = os.getenv("GITHUB_CLIENT_ID")
    client_secret = os.getenv("GITHUB_CLIENT_SECRET")
    if not (client_id and client_secret):
        return None

    from fastmcp.server.auth.providers.github import GitHubProvider

    base_url = os.getenv("OAUTH_BASE_URL", "http://localhost:8000")
    return GitHubProvider(
        client_id=client_id,
        client_secret=client_secret,
        base_url=base_url,
    )


mcp = FastMCP("veristead", auth=_build_auth())


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


@mcp.tool
def handle_natural_language_command(command: str) -> dict:
    """Interpret an ambiguous natural-language request into a proposed device action.

    Use this ONLY for genuinely ambiguous requests (e.g. "I'm cold") where
    the specific device and action aren't stated directly. Deterministic
    commands ("turn off the kitchen light") should call
    execute_device_action directly instead -- skip this tool and its
    Bedrock call entirely for those.

    This tool never executes anything itself. It returns a proposal to
    confirm with the user; call execute_device_action directly afterward
    with the proposed device/action to actually perform it, going through
    the same Verify step as every other action.

    Args:
        command: the natural-language request, e.g. "I'm cold".
    """
    return interpret_command_impl(command)


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
