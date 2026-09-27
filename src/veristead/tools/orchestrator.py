"""In-Server Stateful Orchestrator for Alexa+ (Propose -> Confirm -> Execute).

Provides end-to-end orchestration of natural language commands:
1. Bedrock ambiguity resolution into a verified action proposal with proposal_id.
2. Stateful persistence in SQLite and memory cache.
3. Multi-modal Echo Show card with interactive action chips ([Confirm & Execute], [Cancel]).
4. Verified execution enforcement (Request -> Execute -> Verify -> Confirm) upon confirmation
   or immediate single round-trip when auto_confirm=True.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from veristead.tools import devices
from veristead.tools.cards import (
    RichCard,
    format_proposal_card,
    format_proposal_execution_card,
)
from veristead.tools.devices import execute_device_action_impl
from veristead.tools.intent import interpret_command_impl
from veristead.tools.memory import remember

# In-memory proposal storage cache for fast retrieval and test isolation
_PROPOSALS: dict[str, dict[str, Any]] = {}


def reset_proposals() -> None:
    """Clear in-memory proposal storage cache (used in test fixtures)."""
    _PROPOSALS.clear()


def _get_connection() -> sqlite3.Connection:
    """Obtain SQLite connection and ensure pending_proposals table exists."""
    devices.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(devices.DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS pending_proposals (
            id TEXT PRIMARY KEY,
            command TEXT NOT NULL,
            device TEXT NOT NULL,
            action TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL,
            status TEXT NOT NULL,
            executed_at TEXT,
            execution_result TEXT
        )
        """
    )
    conn.commit()
    return conn


def _store_proposal(proposal: dict[str, Any]) -> None:
    """Store proposal in both in-memory cache and SQLite."""
    proposal_id = proposal["proposal_id"]
    _PROPOSALS[proposal_id] = dict(proposal)

    try:
        with _get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO pending_proposals
                (id, command, device, action, message, created_at, status, executed_at, execution_result)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    proposal_id,
                    proposal.get("command", ""),
                    proposal["device"],
                    proposal["action"],
                    proposal.get("message", ""),
                    proposal.get("created_at", datetime.now(timezone.utc).isoformat()),
                    proposal.get("status", "pending"),
                    proposal.get("executed_at"),
                    json.dumps(proposal.get("execution_result")) if proposal.get("execution_result") else None,
                ),
            )
            conn.commit()
    except Exception:
        # Graceful fallback: memory cache guarantees hermetic test and execution
        pass


def _get_proposal(proposal_id: str) -> dict[str, Any] | None:
    """Retrieve proposal from memory cache or SQLite."""
    if proposal_id in _PROPOSALS:
        return dict(_PROPOSALS[proposal_id])

    try:
        with _get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM pending_proposals WHERE id = ?", (proposal_id,)
            ).fetchone()
            if row:
                record = {
                    "proposal_id": row["id"],
                    "command": row["command"],
                    "device": row["device"],
                    "action": row["action"],
                    "message": row["message"],
                    "created_at": row["created_at"],
                    "status": row["status"],
                    "executed_at": row["executed_at"],
                    "execution_result": (
                        json.loads(row["execution_result"])
                        if row["execution_result"]
                        else None
                    ),
                }
                _PROPOSALS[proposal_id] = record
                return record
    except Exception:
        pass

    return None


def _update_proposal(
    proposal_id: str,
    status: str,
    result: dict[str, Any] | None = None,
) -> None:
    """Update status and execution result of an existing proposal."""
    now_iso = datetime.now(timezone.utc).isoformat()
    if proposal_id in _PROPOSALS:
        _PROPOSALS[proposal_id]["status"] = status
        _PROPOSALS[proposal_id]["executed_at"] = now_iso
        if result is not None:
            _PROPOSALS[proposal_id]["execution_result"] = result

    try:
        with _get_connection() as conn:
            conn.execute(
                """
                UPDATE pending_proposals
                SET status = ?, executed_at = ?, execution_result = ?
                WHERE id = ?
                """,
                (
                    status,
                    now_iso,
                    json.dumps(result) if result is not None else None,
                    proposal_id,
                ),
            )
            conn.commit()
    except Exception:
        pass


def get_pending_proposals_impl() -> list[dict[str, Any]]:
    """Return all pending proposals awaiting confirmation."""
    proposals = []
    try:
        with _get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM pending_proposals WHERE status = 'pending' ORDER BY created_at DESC"
            ).fetchall()
            for row in rows:
                proposals.append({
                    "proposal_id": row["id"],
                    "command": row["command"],
                    "device": row["device"],
                    "action": row["action"],
                    "message": row["message"],
                    "created_at": row["created_at"],
                    "status": row["status"],
                })
    except Exception:
        pass

    # Ensure in-memory cache is included
    for p_id, p in _PROPOSALS.items():
        if p.get("status") == "pending" and not any(r["proposal_id"] == p_id for r in proposals):
            proposals.append(dict(p))

    return proposals


def cancel_proposal_impl(proposal_id: str) -> dict[str, Any]:
    """Cancel a pending action proposal."""
    prop = _get_proposal(proposal_id)
    if not prop:
        return {"status": "error", "proposal_id": proposal_id, "reason": "proposal not found"}
    _update_proposal(proposal_id, "cancelled")
    return {
        "status": "cancelled",
        "proposal_id": proposal_id,
        "message": f"Proposal {proposal_id} cancelled.",
    }


def orchestrate_natural_language_command_impl(
    command: str,
    auto_confirm: bool = False,
    client: Any | None = None,
) -> dict[str, Any]:
    """Orchestrate an ambiguous natural language command end-to-end.

    1. Interprets natural language into a proposed device action.
    2. Stores proposal with a unique proposal_id.
    3. If auto_confirm=True, immediately confirms and executes the verified action loop
       without requiring a second round-trip.
    4. If auto_confirm=False, returns the proposal with interactive action chips for Echo Show.
    """
    if not command or not isinstance(command, str) or not command.strip():
        return {
            "status": "error",
            "command": str(command),
            "reason": "empty command — provide a natural language request like 'I\\'m cold'",
        }

    clean_cmd = command.strip()

    # Step 1: Bedrock ambiguous intent interpretation
    res = interpret_command_impl(clean_cmd, client=client)

    if res.get("status") == "proposed":
        device = res["device"]
        action = res["action"]
        message = res.get("message", f"Set {device} to {action}?")
    else:
        # Fallback for voice shortcuts when Bedrock model ID is not configured in local demo
        norm = clean_cmd.lower()
        device, action, message = None, None, None
        if "cold" in norm:
            device, action, message = "Thermostat", "set:23", "The room feels cold — increase the thermostat to 23°C?"
        elif "hot" in norm or "warm" in norm:
            device, action, message = "Thermostat", "set:20", "The room feels warm — lower the thermostat to 20°C?"
        elif "movie" in norm:
            device, action, message = "Living Room Light", "off", "Movie time — turn off living room lights?"
        elif "night" in norm or "bed" in norm or "sleep" in norm:
            device, action, message = "Living Room Light", "off", "Good night — turn off living room lights?"
        elif "kitchen" in norm and "on" in norm:
            device, action, message = "Kitchen Light", "on", "Turn on the kitchen light?"
        elif "kitchen" in norm and "off" in norm:
            device, action, message = "Kitchen Light", "off", "Turn off the kitchen light?"
        elif "garage" in norm and "open" in norm:
            device, action, message = "Garage Door Opener", "open", "Open the garage door?"
        elif "garage" in norm and "close" in norm:
            device, action, message = "Garage Door Opener", "close", "Close the garage door?"
        elif "lock" in norm and "front door" in norm:
            device, action, message = "Front Door Lock", "lock", "Lock the front door?"
        elif "unlock" in norm and "front door" in norm:
            device, action, message = "Front Door Lock", "unlock", "Unlock the front door?"

        if device is None:
            return res

    proposal_id = f"prop_{uuid.uuid4().hex[:8]}"
    prop_record = {
        "proposal_id": proposal_id,
        "command": clean_cmd,
        "device": device,
        "action": action,
        "message": message,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending",
    }
    _store_proposal(prop_record)

    remember(
        topic="orchestration:proposal",
        detail=f"Proposed '{action}' on {device} for request '{clean_cmd}' (ID: {proposal_id})",
    )

    if auto_confirm:
        # Single round-trip: immediately execute through verified loop
        exec_res = confirm_and_execute_proposal_impl(proposal_id)
        exec_res["auto_confirmed"] = True
        exec_res["command"] = clean_cmd
        return exec_res

    card = format_proposal_card(prop_record)

    return {
        "status": "proposed",
        "orchestrated": True,
        "auto_confirmed": False,
        "proposal_id": proposal_id,
        "command": clean_cmd,
        "device": device,
        "action": action,
        "message": message,
        "requires_confirmation": True,
        "interactive_actions": card.interactive_actions,
        "card": card,
        "voice_speech": message,
    }


def confirm_and_execute_proposal_impl(proposal_id: str) -> dict[str, Any]:
    """Look up a pending proposal and execute it through verified action layer.

    Enforces the full Request -> Execute -> Verify -> Confirm cycle:
    re-reads physical hardware state, prevents false confirmations, records
    telemetry, and updates household memory.
    """
    if not proposal_id or not isinstance(proposal_id, str):
        return {
            "status": "error",
            "proposal_id": str(proposal_id),
            "reason": "invalid proposal_id",
        }

    prop = _get_proposal(proposal_id.strip())
    if not prop:
        return {
            "status": "error",
            "proposal_id": proposal_id,
            "reason": f"proposal '{proposal_id}' not found or expired",
        }

    if prop.get("status") == "executed":
        return {
            "status": "error",
            "proposal_id": proposal_id,
            "reason": f"proposal '{proposal_id}' has already been executed",
        }

    device = prop["device"]
    action = prop["action"]

    # Execute action through the verified execution layer
    exec_result = execute_device_action_impl(device, action)
    exec_status = exec_result.get("status", "unknown")

    # Update proposal record
    _update_proposal(proposal_id, "executed", exec_result)

    remember(
        topic="orchestration:execution",
        detail=f"Confirmed and executed proposal {proposal_id}: '{action}' on {device} -> {exec_status}",
    )

    card = format_proposal_execution_card(prop, exec_result)

    if exec_status == "success":
        voice_speech = f"Confirmed and verified: {device} is now {action}."
    else:
        voice_speech = (
            f"Action on {device} failed verification: {exec_result.get('reason', 'unresponsive')}."
        )

    return {
        "status": exec_status,
        "orchestrated": True,
        "proposal_id": proposal_id,
        "device": device,
        "action": action,
        "verified_state": exec_result.get("new_state"),
        "execution": exec_result,
        "reason": exec_result.get("reason"),
        "card": card,
        "voice_speech": voice_speech,
    }
