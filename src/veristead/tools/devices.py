"""Mocked smart-home device layer (Capability Charter, Pillars 1-4, 6).

A local SQLite-backed "virtual home" stands in for real hardware -- the
mock is explicit and documented, not data passed off as real. Every
mutating action follows Request -> Execute -> Verify -> Confirm: the
device state is re-read after acting, and the response is built from
what's actually true, not assumed from the request.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from veristead.tools.memory import remember

DB_PATH = Path(__file__).resolve().parents[3] / "data" / "devices.db"

# Seed household -- a handful of devices across a few rooms, enough to
# demo routines, partial failures, and room-level resolution.
_SEED_DEVICES = [
    ("living_room_light", "Living Room Light", "living room", "light", {"power": "off"}),
    ("bedroom_light", "Bedroom Light", "bedroom", "light", {"power": "off"}),
    ("kitchen_light", "Kitchen Light", "kitchen", "light", {"power": "off"}),
    ("thermostat", "Thermostat", "living room", "thermostat", {"temperature": 21}),
    ("front_door_lock", "Front Door Lock", "entryway", "lock", {"locked": True}),
]

# Named multi-device routines -- the orchestrator's building blocks.
_ROUTINES = {
    "good night": [
        ("living_room_light", "off"),
        ("bedroom_light", "off"),
        ("kitchen_light", "off"),
        ("front_door_lock", "lock"),
        ("thermostat", "set:18"),
    ],
    "good morning": [
        ("kitchen_light", "on"),
        ("thermostat", "set:21"),
    ],
}


@contextmanager
def _connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS devices (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                room TEXT NOT NULL,
                type TEXT NOT NULL,
                state TEXT NOT NULL,
                online INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        count = conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0]
        if count == 0:
            for device_id, name, room, dtype, state in _SEED_DEVICES:
                conn.execute(
                    "INSERT INTO devices (id, name, room, type, state, online) "
                    "VALUES (?, ?, ?, ?, ?, 1)",
                    (device_id, name, room, dtype, json.dumps(state)),
                )
        yield conn
        conn.commit()
    finally:
        conn.close()


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "room": row["room"],
        "type": row["type"],
        "state": json.loads(row["state"]),
        "online": bool(row["online"]),
    }


def get_device_status_impl(name_or_room: str | None = None) -> list[dict]:
    """Return current status for matching devices (Verify's read path)."""
    with _connection() as conn:
        if name_or_room:
            needle = f"%{name_or_room.strip().lower()}%"
            rows = conn.execute(
                "SELECT * FROM devices WHERE lower(name) LIKE ? OR lower(room) LIKE ?",
                (needle, needle),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM devices").fetchall()
    return [_row_to_dict(r) for r in rows]


def get_room_devices_impl(room: str) -> list[dict]:
    """Resolve a room name to its devices (e.g. "living room" -> lights + thermostat)."""
    with _connection() as conn:
        rows = conn.execute(
            "SELECT * FROM devices WHERE lower(room) = ?", (room.strip().lower(),)
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def _apply_action(state: dict, dtype: str, action: str) -> dict | None:
    """Return updated state for a valid action, or None if unsupported."""
    action = action.strip().lower()
    if dtype in ("light", "plug") and action in ("on", "off"):
        return {**state, "power": action}
    if dtype == "lock" and action in ("lock", "unlock"):
        return {**state, "locked": action == "lock"}
    if dtype == "thermostat" and action.startswith("set:"):
        try:
            temperature = int(action.split(":", 1)[1])
        except ValueError:
            return None
        return {**state, "temperature": temperature}
    return None


def _find_device(conn: sqlite3.Connection, device_query: str) -> tuple[sqlite3.Row | None, str | None]:
    """Find a single device matching query via exact match or bidirectional substring match.
    
    Returns (row, None) if exactly one match found.
    Returns (None, reason) if no matches found or if ambiguous (multiple matches).
    """
    needle = device_query.strip().lower()
    if not needle:
        return None, "device not found"

    rows = conn.execute("SELECT * FROM devices").fetchall()
    
    # 1. Exact match (name or id)
    for r in rows:
        if r["name"].lower() == needle or r["id"].lower() == needle or r["id"].lower() == needle.replace(" ", "_"):
            return r, None

    # 2. Bidirectional substring match
    matches = []
    for r in rows:
        r_name = r["name"].lower()
        if r_name in needle or needle in r_name:
            matches.append(r)

    if not matches:
        return None, "device not found"
    if len(matches) == 1:
        return matches[0], None

    match_names = ", ".join(r["name"] for r in matches)
    return None, f"ambiguous device name, matches multiple devices: {match_names}"


def execute_device_action_impl(device: str, action: str) -> dict:
    """Request -> Execute -> Verify -> Confirm for a single device action.

    Never reports success without re-reading the device's actual state
    after acting. Writes every action to household memory automatically.
    """
    with _connection() as conn:
        row, error_reason = _find_device(conn, device)

        if row is None:
            return {"status": "error", "device": device, "reason": error_reason}

        current = _row_to_dict(row)

        if not current["online"]:
            remember(
                topic=f"device:{current['name'].lower()}",
                detail=f"Attempted action '{action}' on {current['name']} failed (offline)",
            )
            return {
                "status": "failed",
                "device": current["name"],
                "reason": "device is offline",
            }

        new_state = _apply_action(current["state"], current["type"], action)
        if new_state is None:
            return {
                "status": "error",
                "device": current["name"],
                "reason": f"unsupported action '{action}' for {current['type']}",
            }

        conn.execute(
            "UPDATE devices SET state = ? WHERE id = ?",
            (json.dumps(new_state), current["id"]),
        )
        # Verify: re-read what was actually written, don't trust the write blindly.
        verified = conn.execute(
            "SELECT * FROM devices WHERE id = ?", (current["id"],)
        ).fetchone()
        verified_dict = _row_to_dict(verified)

        remember(
            topic=f"device:{verified_dict['name'].lower()}",
            detail=f"Executed '{action}' on {verified_dict['name']} in {verified_dict['room']} (state: {json.dumps(verified_dict['state'])})",
        )

    return {
        "status": "success",
        "device": verified_dict["name"],
        "new_state": verified_dict["state"],
    }


def run_routine_impl(routine_name: str) -> dict:
    """Run a named multi-device routine, reporting partial failures honestly.

    This is the orchestrator: it chains execute_device_action_impl calls
    and returns a consolidated result rather than a blanket "done."
    """
    normalized = routine_name.strip().lower()
    steps = _ROUTINES.get(normalized)
    if steps is None:
        return {
            "status": "error",
            "routine": routine_name,
            "reason": f"unknown routine (known: {', '.join(_ROUTINES)})",
        }

    results = [execute_device_action_impl(device, action) for device, action in steps]
    succeeded = [r for r in results if r["status"] == "success"]
    failed = [r for r in results if r["status"] != "success"]
    summary = (
        f"{len(succeeded)} succeeded, {len(failed)} failed"
        + (f" ({', '.join(r['device'] for r in failed)})" if failed else "")
    )

    remember(topic=f"routine:{normalized}", detail=summary)

    return {
        "status": "ok" if not failed else "partial_failure",
        "routine": routine_name,
        "results": results,
        "summary": summary,
    }


def simulate_offline_device_impl(device: str, offline: bool = True) -> dict:
    """Demo/debug tool: deliberately toggle a device offline to trigger the
    partial-failure scenario on command, rather than hoping it happens
    naturally during a live demo."""
    with _connection() as conn:
        row, error_reason = _find_device(conn, device)
        if row is None:
            return {"status": "error", "device": device, "reason": error_reason}

        conn.execute(
            "UPDATE devices SET online = ? WHERE id = ?", (0 if offline else 1, row["id"])
        )

    return {"device": row["name"], "online": not offline}
