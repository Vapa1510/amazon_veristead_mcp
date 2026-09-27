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

import logging
import os
import uvicorn
from starlette.middleware import Middleware
from starlette.types import ASGIApp, Receive, Scope, Send

from dotenv import load_dotenv
from fastmcp import FastMCP

logger = logging.getLogger("veristead")

from veristead.tools.adapters import get_adapter_status_impl
from veristead.tools.cards import (
    format_adapter_status_card,
    format_device_status_card,
    format_replenishment_card,
    format_routine_result_card,
    format_security_alert_card,
    format_telemetry_card,
)
from veristead.tools.telemetry import (
    get_reliability_metrics_impl,
    get_verification_telemetry_impl,
)
from veristead.tools.devices import (
    execute_device_action_impl,
    get_device_status_impl,
    get_room_devices_impl,
    run_routine_impl,
    simulate_hardware_drift_impl,
    simulate_offline_device_impl,
)
from veristead.tools.cloudwatch import get_execution_audit_trail_impl
from veristead.tools.intent import interpret_command_impl
from veristead.tools.memory import (
    forget_topic_impl,
    recall_context_impl,
    view_memory_impl,
)
from veristead.tools.replenishment import propose_device_replenishment_impl
from veristead.tools.orchestrator import (
    confirm_and_execute_proposal_impl,
    orchestrate_natural_language_command_impl,
)
from veristead.ui import register_simulator_routes
try:
    from veristead.tools.alerts import escalate_security_alert_impl
except ImportError:
    from veristead.tools.security import escalate_security_alert_impl

load_dotenv()


def _build_auth():
    """Return a GitHubProvider auth object if credentials are configured,
    otherwise None (unauthenticated local-dev mode).

    In production mode (VERISTEAD_ENV=production or REQUIRE_AUTH=true),
    OAuth credentials are strictly required. If credentials are missing,
    the server refuses to start in open mode and raises an explicit RuntimeError.
    """
    env_mode = os.getenv("VERISTEAD_ENV", "").strip().lower()
    require_auth_flag = os.getenv("REQUIRE_AUTH", "").strip().lower() in ("true", "1", "yes")
    is_production = env_mode == "production" or require_auth_flag

    client_id = os.getenv("GITHUB_CLIENT_ID")
    client_secret = os.getenv("GITHUB_CLIENT_SECRET")
    base_url = os.getenv("OAUTH_BASE_URL")

    if is_production and (not client_id or not client_secret):
        raise RuntimeError("Production mode requires OAuth credentials. Server will not fall open.")

    if not (client_id and client_secret and base_url):
        logger.warning(
            "OAuth env incomplete (need GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET, "
            "OAUTH_BASE_URL) — starting in OPEN (unauthenticated) mode. "
            "Do not expose this mode on a public URL."
        )
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
def get_device_status(name_or_room: str | None = None) -> dict:
    """Get current status for devices matching a name or room.

    Returns structured device data plus a visual dashboard card for
    rich rendering in MCP clients.

    Args:
        name_or_room: device name or room to filter by (substring match).
            Omit to get every device's status.
    """
    devices = get_device_status_impl(name_or_room)
    return {
        "devices": devices,
        "card": format_device_status_card(devices),
    }


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
            locks, "open"/"close" for garage doors, "set:<temperature>"
            for the thermostat (10-32 C).
    """
    return execute_device_action_impl(device, action)


@mcp.tool
def run_routine(routine_name: str) -> dict:
    """Run a named multi-device routine (e.g. "good night", "good morning", "movie time").

    Reports a consolidated result across every device touched, including
    any that failed or were offline — never a blanket "done." Includes
    a visual summary card for rich rendering in MCP clients.

    Args:
        routine_name: the routine to run.
    """
    result = run_routine_impl(routine_name)
    result["card"] = format_routine_result_card(result)
    return result


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
def simulate_hardware_drift(device: str, drift: bool = True) -> dict:
    """Demo/test tool: simulate silent physical hardware write failure or state drift.

    When drift is enabled, hardware silently drops or corrupts mutating actions.
    Veristead's post-execution verification re-reads state, detects the discrepancy,
    and returns a verified failure instead of false-positive confirmation.

    Args:
        device: Device name, e.g. "Kitchen Light".
        drift: True to simulate write failure, False to restore normal behavior.
    """
    return simulate_hardware_drift_impl(device, drift)


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


@mcp.tool
def propose_device_replenishment(device: str) -> dict:
    """Diagnose device failure or offline status and propose consumable replenishment.

    Adheres to Pillars 4 & 6: diagnoses root causes (e.g. dead battery in Smart Lock,
    burned-out bulb in Light fixture, backup battery depletion in Thermostat) and
    creates a structured Amazon Cart replenishment proposal with ASIN and pricing,
    requiring explicit user confirmation before any order is placed. Never auto-orders.

    Args:
        device: device name or id, e.g. "Front Door Lock", "Kitchen Light", or "Thermostat".
    """
    result = propose_device_replenishment_impl(device)
    result["card"] = format_replenishment_card(result)
    return result


@mcp.tool
def escalate_security_alert(device: str, reason: str, routine: str | None = None) -> dict:
    """Escalate a critical smart-home security failure via Amazon SNS.

    Dispatches an urgent alert when security-critical hardware (locks, garage doors)
    fails to secure. If AWS_SNS_TOPIC_ARN is not configured, provides a verified
    simulation fallback so tests and evaluations run hermetically.

    Args:
        device: the security-critical device that failed (e.g., "Front Door Lock").
        reason: reason for failure (e.g., "device is offline").
        routine: optional routine name during which failure occurred (e.g., "good night").
    """
    result = escalate_security_alert_impl(device, reason, routine)
    result["card"] = format_security_alert_card(result)
    return result


@mcp.tool
def get_adapter_status() -> dict:
    """Inspect smart-home device adapter architecture and hardware integration status.

    Returns the active adapter configuration (MockSQLite, Home Assistant REST/WebSocket,
    or Matter 1.3 Bridge) and hardware readiness data, confirming how real devices
    connect without breaking hermetic test execution. Includes a visual dashboard card.
    """
    status = get_adapter_status_impl()
    status["card"] = format_adapter_status_card(status)
    return status


@mcp.tool
def get_verification_telemetry() -> dict:
    """Retrieve quantitative household reliability stats and verification telemetry.

    Tracks real-time household reliability stats: Total Verified Executions, Verification Success Rate,
    Routine Partial Failure Rate (contrasting with the 18-24% industry silent failure baseline),
    Autonomous Self-Healing Recovery Rate, and Security Escalation Counts. Includes a visual dashboard card.
    """
    metrics = get_verification_telemetry_impl()
    metrics["card"] = format_telemetry_card(metrics)
    return metrics


@mcp.tool
def get_reliability_metrics() -> dict:
    """Retrieve quantitative reliability metrics, verification telemetry, and impact benchmarks.

    Tracks verified executions, silent failures prevented (benchmarked against the 18.4%
    industry routine failure rate), autonomous self-healing compensations, and perimeter
    security escalations across sessions. Includes a visual dashboard card.
    """
    return get_verification_telemetry()


@mcp.tool
def get_execution_audit_trail(limit: int = 10) -> list[dict]:
    """Retrieve cryptographically verifiable execution receipts from AWS CloudWatch Logs.

    Every hardware command, state verification, and security escalation is logged
    with SHA-256 tamper-evident integrity hashes to CloudWatch Logs.

    Args:
        limit: Maximum number of audit receipts to return (default 10).
    """
    return get_execution_audit_trail_impl(limit=limit)


@mcp.tool
def confirm_and_execute_proposal(proposal_id: str) -> dict:
    """Confirm and execute a pending natural-language action proposal.

    Looks up a pending proposal stored in the stateful orchestrator, executes
    the proposed action through the verified execution layer (enforcing the
    Verify step: Request -> Execute -> Verify -> Confirm), records telemetry,
    and updates household memory.

    Args:
        proposal_id: the unique identifier of the pending proposal (e.g. 'prop_a1b2c3d4').
    """
    return confirm_and_execute_proposal_impl(proposal_id)


@mcp.tool
def orchestrate_natural_language_command(command: str, auto_confirm: bool = False) -> dict:
    """Orchestrate an ambiguous natural-language command end-to-end (Propose -> Confirm -> Execute).

    Interprets natural language into a verified device action proposal, assigns a
    proposal_id, and attaches interactive visual action chips for Echo Show and MCP Apps.
    If auto_confirm is True, immediately executes the verified action loop in a single
    round-trip without requiring the client to manually parse device/action arguments.

    Args:
        command: the natural-language command (e.g. "I'm cold", "turn off the bedroom light").
        auto_confirm: if True, immediately confirm and execute the verified action loop.
    """
    return orchestrate_natural_language_command_impl(command, auto_confirm=auto_confirm)


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


def create_app() -> ASGIApp:
    """Build the Starlette application with FastMCP and the Echo Show simulator mounted."""
    app = mcp.http_app(
        transport="streamable-http",
        middleware=[Middleware(StripWWWAuthenticateMiddleware)],
    )
    register_simulator_routes(app)
    return app


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    if _auth is None:
        logger.warning(
            "Running without OAuth — suitable for local MCP Inspector only"
        )
    host = os.getenv("MCP_HOST", "0.0.0.0")
    port = int(os.getenv("MCP_PORT", "8000"))
    app = create_app()
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
