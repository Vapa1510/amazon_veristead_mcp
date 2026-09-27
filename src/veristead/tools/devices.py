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

# Reasonable residential temperature bounds for the thermostat (Celsius & Fahrenheit).
THERMOSTAT_MIN_C = 10
THERMOSTAT_MAX_C = 32
THERMOSTAT_MIN_F = 50
THERMOSTAT_MAX_F = 90

# Seed household -- 10 devices across 7 rooms, enough variety to demo
# routines, partial failures, room-level resolution, and ambiguous intent.
_SEED_DEVICES = [
    ("living_room_light", "Living Room Light", "living room", "light", {"power": "off"}),
    ("bedroom_light", "Bedroom Light", "bedroom", "light", {"power": "off"}),
    ("kitchen_light", "Kitchen Light", "kitchen", "light", {"power": "off"}),
    ("thermostat", "Thermostat", "living room", "thermostat", {"temperature": 21}),
    ("front_door_lock", "Front Door Lock", "entryway", "lock", {"locked": True}),
    ("garage_door_opener", "Garage Door Opener", "garage", "garage", {"open": False}),
    ("bathroom_fan", "Bathroom Fan", "bathroom", "plug", {"power": "off"}),
    ("office_desk_lamp", "Office Desk Lamp", "office", "light", {"power": "off"}),
    ("bedroom_smart_plug", "Bedroom Smart Plug", "bedroom", "plug", {"power": "off"}),
    ("back_door_lock", "Back Door Lock", "garage", "lock", {"locked": True}),
]

# Named multi-device routines -- the orchestrator's building blocks.
_ROUTINES = {
    "good night": [
        ("living_room_light", "off"),
        ("bedroom_light", "off"),
        ("kitchen_light", "off"),
        ("office_desk_lamp", "off"),
        ("front_door_lock", "lock"),
        ("back_door_lock", "lock"),
        ("thermostat", "set:18"),
    ],
    "good morning": [
        ("kitchen_light", "on"),
        ("thermostat", "set:21"),
    ],
    "movie time": [
        ("living_room_light", "off"),
        ("office_desk_lamp", "off"),
        ("thermostat", "set:20"),
    ],
}

# Registry for simulated hardware write failure / state drift
_DRIFTED_DEVICES: set[str] = set()


@contextmanager
def _connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    # timeout= covers the Python sqlite3 busy wait; busy_timeout is the
    # engine-side equivalent. WAL allows concurrent readers during writes.
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
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
                # INSERT OR IGNORE softens the first-boot seed race under
                # concurrent connections that both see an empty table.
                conn.execute(
                    "INSERT OR IGNORE INTO devices (id, name, room, type, state, online) "
                    "VALUES (?, ?, ?, ?, ?, 1)",
                    (device_id, name, room, dtype, json.dumps(state)),
                )
        else:
            # Migrate legacy garage seed that incorrectly used type=plug.
            conn.execute(
                "UPDATE devices SET type = 'garage', state = ? "
                "WHERE id = 'garage_door_opener' AND type = 'plug'",
                (json.dumps({"open": False}),),
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
    try:
        from veristead.adapters import MockSQLiteAdapter, get_active_adapter
        adapter = get_active_adapter()
        if not isinstance(adapter, MockSQLiteAdapter):
            return adapter.get_devices(name_or_room)
    except Exception:
        pass

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
    try:
        from veristead.adapters import MockSQLiteAdapter, get_active_adapter
        adapter = get_active_adapter()
        if not isinstance(adapter, MockSQLiteAdapter):
            return adapter.get_room_devices(room)
    except Exception:
        pass

    with _connection() as conn:
        rows = conn.execute(
            "SELECT * FROM devices WHERE lower(room) = ?", (room.strip().lower(),)
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def _parse_temperature(val_str: str) -> tuple[int | None, str | None]:
    """Parse temperature input in Celsius or Fahrenheit within residential safe bounds.

    Residential bounds: 10°C to 32°C / 50°F to 90°F.
    Returns (celsius_temp, None) on success, or (None, reject_reason) on failure.
    """
    if not val_str or not isinstance(val_str, str):
        return None, f"invalid temperature '{val_str}'"
    clean = val_str.strip().lower()
    is_f = False
    is_c = False
    if clean.endswith("f"):
        is_f = True
        clean = clean[:-1].strip()
    elif clean.endswith("c"):
        is_c = True
        clean = clean[:-1].strip()

    try:
        val = float(clean)
    except ValueError:
        return None, f"invalid temperature '{val_str}'"

    if is_f:
        if not (THERMOSTAT_MIN_F <= val <= THERMOSTAT_MAX_F):
            return None, (
                f"temperature {val_str} out of range "
                f"({THERMOSTAT_MIN_F}–{THERMOSTAT_MAX_F}°F safe residential bounds)"
            )
        celsius = int(round((val - 32) * 5 / 9))
        return celsius, None

    if is_c:
        if not (THERMOSTAT_MIN_C <= val <= THERMOSTAT_MAX_C):
            return None, (
                f"temperature {val_str} out of range "
                f"({THERMOSTAT_MIN_C}–{THERMOSTAT_MAX_C}°C safe residential bounds)"
            )
        return int(round(val)), None

    # Implicit unit:
    # 10..32 is Celsius
    if THERMOSTAT_MIN_C <= val <= THERMOSTAT_MAX_C:
        return int(round(val)), None

    # 50..90 is Fahrenheit
    if THERMOSTAT_MIN_F <= val <= THERMOSTAT_MAX_F:
        celsius = int(round((val - 32) * 5 / 9))
        return celsius, None

    return None, (
        f"temperature {val_str} out of range "
        f"({THERMOSTAT_MIN_C}-{THERMOSTAT_MAX_C} C / {THERMOSTAT_MIN_F}-{THERMOSTAT_MAX_F} F safe residential bounds)"
    )


def _apply_action(state: dict, dtype: str, action: str) -> dict | None:
    """Return updated state for a valid action, or None if unsupported."""
    if not action or not isinstance(action, str):
        return None
    action = action.strip().lower()
    if dtype in ("light", "plug") and action in ("on", "off"):
        return {**state, "power": action}
    if dtype == "lock" and action in ("lock", "unlock"):
        return {**state, "locked": action == "lock"}
    if dtype in ("garage", "cover") and action in ("open", "close"):
        return {**state, "open": action == "open"}
    if dtype == "thermostat" and action.startswith("set:"):
        val_str = action.split(":", 1)[1].strip()
        temperature, _ = _parse_temperature(val_str)
        if temperature is None:
            return None
        return {**state, "temperature": temperature}
    return None


def _action_reject_reason(dtype: str, action: str) -> str:
    """Human-readable reason when _apply_action returns None."""
    if not action or not isinstance(action, str):
        return f"unsupported action '{action}' for {dtype}"
    action = action.strip().lower()
    if dtype in ("garage", "cover"):
        if action in ("on", "off"):
            return (
                f"garage door opener does not support '{action}' — "
                "use 'open' or 'close' instead"
            )
        return f"unsupported action '{action}' for {dtype} — use 'open' or 'close'"
    if dtype == "thermostat" and action.startswith("set:"):
        val_str = action.split(":", 1)[1].strip()
        _, err = _parse_temperature(val_str)
        if err:
            return err
        return f"unsupported action '{action}' for {dtype}"
    return f"unsupported action '{action}' for {dtype}"


def _find_device(conn: sqlite3.Connection, device_query: str) -> tuple[sqlite3.Row | None, str | None]:
    """Find a single device matching query via exact match or bidirectional substring match.

    Returns (row, None) if exactly one match found.
    Returns (None, reason) if no matches found or if ambiguous (multiple matches).
    """
    if not device_query or not isinstance(device_query, str):
        return None, "device not found"

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
    after acting and confirming it matches the expected post-action state.
    Memory writes happen after the devices DB connection is released so
    we do not hold the devices lock across a nested SQLite open.
    """
    if not device or not isinstance(device, str):
        return {"status": "error", "device": str(device), "reason": "device not found"}
    if not action or not isinstance(action, str):
        return {"status": "error", "device": device, "reason": f"unsupported action '{action}'"}

    try:
        from veristead.adapters import MockSQLiteAdapter, get_active_adapter
        adapter = get_active_adapter()
        if not isinstance(adapter, MockSQLiteAdapter):
            res = adapter.execute_action(device, action)
            dev_name = res.get("device", device)
            res_status = res.get("status", "unknown")
            if res_status == "success":
                remember(
                    topic=f"device:{dev_name.lower()}",
                    detail=f"Executed '{action}' on {dev_name} via {adapter.name} (state: {json.dumps(res.get('new_state', {}))})",
                )
            else:
                remember(
                    topic=f"device:{dev_name.lower()}",
                    detail=f"Attempted action '{action}' on {dev_name} via {adapter.name} failed ({res.get('reason')})",
                )
            try:
                from veristead.tools.telemetry import record_action_result
                record_action_result(
                    device=dev_name,
                    action=action,
                    status=res_status,
                    failure_reason=res.get("reason"),
                )
            except Exception:
                pass
            return res
    except Exception:
        pass

    memory_topic: str | None = None
    memory_detail: str | None = None
    result: dict

    with _connection() as conn:
        row, error_reason = _find_device(conn, device)

        if row is None:
            err_res = {"status": "error", "device": device, "reason": error_reason}
            try:
                from veristead.tools.telemetry import record_action_result
                record_action_result(device, action, "error", error_reason)
            except Exception:
                pass
            return err_res

        current = _row_to_dict(row)

        if not current["online"]:
            memory_topic = f"device:{current['name'].lower()}"
            memory_detail = (
                f"Attempted action '{action}' on {current['name']} failed (offline)"
            )
            result = {
                "status": "failed",
                "device": current["name"],
                "reason": "device is offline",
            }
        else:
            expected_state = _apply_action(current["state"], current["type"], action)
            if expected_state is None:
                rej_reason = _action_reject_reason(current["type"], action)
                err_res = {
                    "status": "error",
                    "device": current["name"],
                    "reason": rej_reason,
                }
                try:
                    from veristead.tools.telemetry import record_action_result
                    record_action_result(current["name"], action, "error", rej_reason)
                except Exception:
                    pass
                return err_res

            # Hardware execution: if hardware drift is simulated, the hardware silently drops the write
            is_drifted = (
                current["id"] in _DRIFTED_DEVICES
                or current["name"].lower() in _DRIFTED_DEVICES
            )
            if not is_drifted:
                conn.execute(
                    "UPDATE devices SET state = ? WHERE id = ?",
                    (json.dumps(expected_state), current["id"]),
                )

            # Verify: re-read the device's actual state directly from hardware/storage
            verified = conn.execute(
                "SELECT * FROM devices WHERE id = ?", (current["id"],)
            ).fetchone()
            verified_dict = _row_to_dict(verified)

            # Strict equality check: expected_state vs actual_state
            if verified_dict["state"] == expected_state:
                memory_topic = f"device:{verified_dict['name'].lower()}"
                memory_detail = (
                    f"Executed '{action}' on {verified_dict['name']} in "
                    f"{verified_dict['room']} (state: {json.dumps(verified_dict['state'])})"
                )
                result = {
                    "status": "success",
                    "device": verified_dict["name"],
                    "new_state": verified_dict["state"],
                }
            else:
                memory_topic = f"device:{verified_dict['name'].lower()}"
                memory_detail = (
                    f"Verification failed for '{action}' on {verified_dict['name']}: "
                    f"expected {json.dumps(expected_state)}, got {json.dumps(verified_dict['state'])}"
                )
                result = {
                    "status": "failed",
                    "device": verified_dict["name"],
                    "reason": "state verification failed",
                    "expected_state": expected_state,
                    "actual_state": verified_dict["state"],
                }

    if memory_topic is not None and memory_detail is not None:
        remember(topic=memory_topic, detail=memory_detail)

    try:
        from veristead.tools.telemetry import record_action_result
        record_action_result(
            device=result.get("device", device),
            action=action,
            status=result.get("status", "unknown"),
            failure_reason=result.get("reason"),
        )
    except Exception:
        pass

    try:
        from veristead.tools.cloudwatch import log_execution_receipt
        log_execution_receipt(
            device=result.get("device", device),
            action=action,
            status=result.get("status", "unknown"),
            expected_state=result.get("expected_state") if result.get("status") == "failed" else result.get("new_state"),
            actual_state=result.get("actual_state") if result.get("status") == "failed" else result.get("new_state"),
        )
    except Exception:
        pass

    return result


# Self-healing fallback rules by (device_id, action) -> (substitute_device_name, compensating_action, reason)
_COMPENSATING_RULES: dict[tuple[str, str], tuple[str, str, str]] = {
    ("kitchen_light", "off"): (
        "Living Room Light",
        "off",
        "ensure adjacent living room light is off for evening zone safety",
    ),
    ("kitchen_light", "on"): (
        "Living Room Light",
        "on",
        "provide illumination via adjacent living room light",
    ),
    ("bedroom_light", "off"): (
        "Bedroom Smart Plug",
        "off",
        "cut power to bedroom accessories and secondary lamps for sleep safety",
    ),
    ("living_room_light", "off"): (
        "Office Desk Lamp",
        "off",
        "ensure adjacent workspace lighting is turned off",
    ),
    ("office_desk_lamp", "off"): (
        "Living Room Light",
        "off",
        "ensure adjacent living room lighting is turned off",
    ),
    ("front_door_lock", "lock"): (
        "Back Door Lock",
        "lock",
        "verify and secure secondary perimeter entry point",
    ),
    ("garage_door_opener", "close"): (
        "Back Door Lock",
        "lock",
        "lock interior garage door to prevent unauthorized home access",
    ),
    ("back_door_lock", "lock"): (
        "Front Door Lock",
        "lock",
        "reinforce main entryway lock",
    ),
}


def _attempt_compensating_action(
    failed_device_name: str,
    action: str,
    routine_name: str,
) -> dict | None:
    """Execute an autonomous compensating action when a routine step fails.

    Checks room topology and device substitution rules, then executes a
    verified compensating action so the home remains in a safe state.
    """
    if not failed_device_name or not isinstance(failed_device_name, str):
        return None
    if not action or not isinstance(action, str):
        return None

    normalized_action = action.strip().lower()
    norm_routine = (routine_name or "").strip().lower()

    substitute_device: str | None = None
    compensating_action: str | None = None
    comp_reason: str | None = None

    with _connection() as conn:
        row, _ = _find_device(conn, failed_device_name)
        if row is not None:
            dev_id = row["id"].lower()
            dev_room = row["room"].lower()
            failed_type = row["type"]

            rule = _COMPENSATING_RULES.get((dev_id, normalized_action))
            if rule:
                cand_sub, cand_act, cand_reason = rule
                # Check if the rule's intended substitute device is online
                sub_row, _ = _find_device(conn, cand_sub)
                if sub_row is not None and sub_row["online"]:
                    substitute_device, compensating_action, comp_reason = cand_sub, cand_act, cand_reason

            if not substitute_device:
                # Dynamic room topology lookup: find another online device in the same room
                same_room = conn.execute(
                    "SELECT * FROM devices WHERE lower(room) = ? AND id != ? AND online = 1",
                    (dev_room, dev_id),
                ).fetchall()
                if same_room:
                    # Thermostats cannot be compensated by turning random room lights on/off
                    compatible_cands = []
                    for c in same_room:
                        c_type = c["type"]
                        if failed_type in ("light", "plug") and c_type in ("light", "plug"):
                            compatible_cands.append(c)
                        elif failed_type in ("lock", "garage") and c_type in ("lock", "garage"):
                            compatible_cands.append(c)

                    if compatible_cands:
                        # Prefer same type first
                        compatible_cands.sort(key=lambda c: 0 if c["type"] == failed_type else 1)
                        cand = compatible_cands[0]
                        substitute_device = cand["name"]
                        cand_type = cand["type"]
                        if cand_type in ("light", "plug"):
                            if "off" in normalized_action or norm_routine in ("good night", "movie time"):
                                compensating_action = "off"
                            elif "on" in normalized_action or norm_routine in ("good morning",):
                                compensating_action = "on"
                            else:
                                compensating_action = "off"
                        elif cand_type in ("lock", "garage"):
                            compensating_action = "lock" if "lock" in normalized_action or "close" in normalized_action or norm_routine == "good night" else "unlock"
                        comp_reason = f"room topology fallback ({cand['room']})"

            # If rule substitute was offline and no alternative online device in the room was found,
            # execute the rule substitute anyway so the failure is re-read and verified honestly
            if not substitute_device and rule:
                substitute_device, compensating_action, comp_reason = rule

    if not substitute_device or not compensating_action:
        return None

    if substitute_device.lower() == failed_device_name.lower():
        return None

    comp_result = execute_device_action_impl(substitute_device, compensating_action)
    comp_status = comp_result.get("status", "unknown")

    if comp_status == "success":
        note = (
            f"Self-healing: compensated {failed_device_name} failure using "
            f"{comp_result.get('device', substitute_device)} ({compensating_action})"
        )
    else:
        note = (
            f"Self-healing: attempted compensation for {failed_device_name} using "
            f"{comp_result.get('device', substitute_device)} ({compensating_action}) "
            f"but substitute was {comp_status}"
        )

    comp_entry = {
        "failed_device": failed_device_name,
        "attempted_action": action,
        "substitute_device": comp_result.get("device", substitute_device),
        "compensating_action": compensating_action,
        "status": comp_status,
        "reason": comp_reason or "autonomous self-healing compensation",
        "verified_state": comp_result.get("new_state"),
        "note": note,
    }

    remember(topic="self_healing:compensation", detail=comp_entry["note"])

    try:
        from veristead.tools.telemetry import record_compensation
        record_compensation(
            failed_device=failed_device_name,
            substitute_device=comp_result.get("device", substitute_device),
            compensating_action=compensating_action,
            status=comp_status,
        )
    except Exception:
        pass

    return comp_entry


def run_routine_impl(routine_name: str) -> dict:
    """Run a named multi-device routine, reporting partial failures honestly.

    This is the orchestrator: it chains execute_device_action_impl calls,
    executes self-healing compensations when steps fail, triggers security
    escalation for perimeter devices, and returns a consolidated result.
    """
    if not routine_name or not isinstance(routine_name, str):
        return {
            "status": "error",
            "routine": str(routine_name),
            "reason": f"unknown routine (known: {', '.join(_ROUTINES)})",
        }
    normalized = routine_name.strip().lower()
    steps = _ROUTINES.get(normalized)
    if steps is None:
        return {
            "status": "error",
            "routine": routine_name,
            "reason": f"unknown routine (known: {', '.join(_ROUTINES)})",
        }

    results = []
    compensations = []
    security_alerts = []

    try:
        from veristead.tools.alerts import escalate_security_alert_impl, is_security_critical
    except ImportError:
        from veristead.tools.security import escalate_security_alert_impl, is_security_critical

    for device, action in steps:
        step_result = execute_device_action_impl(device, action)
        results.append(step_result)

        if step_result.get("status") != "success":
            failed_device_name = step_result.get("device", device)
            failed_reason = step_result.get("reason", "failed")

            # 1. Autonomous Self-Healing Fallback
            comp = _attempt_compensating_action(failed_device_name, action, normalized)
            if comp is not None:
                compensations.append(comp)

            # 2. AWS SNS Security Escalation for perimeter-critical devices
            if is_security_critical(failed_device_name):
                alert = escalate_security_alert_impl(
                    device=failed_device_name,
                    reason=failed_reason,
                    routine=normalized,
                )
                security_alerts.append(alert)

    succeeded = [r for r in results if r["status"] == "success"]
    failed = [r for r in results if r["status"] != "success"]
    summary = (
        f"{len(succeeded)} succeeded, {len(failed)} failed"
        + (f" ({', '.join(r['device'] for r in failed)})" if failed else "")
    )
    if compensations:
        comp_notes = ", ".join(
            f"{c['substitute_device']} ({c['compensating_action']})"
            for c in compensations
            if c.get("status") == "success"
        )
        if comp_notes:
            summary += f" [Self-healing: compensated via {comp_notes}]"

    remember(topic=f"routine:{normalized}", detail=summary)

    try:
        from veristead.tools.telemetry import record_routine
        record_routine(
            routine_name=normalized,
            status="ok" if not failed else "partial_failure",
            step_count=len(steps),
            failed_count=len(failed),
        )
    except Exception:
        pass

    return {
        "status": "ok" if not failed else "partial_failure",
        "routine": routine_name,
        "results": results,
        "compensations": compensations,
        "security_alerts": security_alerts,
        "summary": summary,
    }


def simulate_offline_device_impl(device: str, offline: bool = True) -> dict:
    """Demo/debug tool: deliberately toggle a device offline to trigger the
    partial-failure scenario on command, rather than hoping it happens
    naturally during a live demo."""
    if not device or not isinstance(device, str):
        return {"status": "error", "device": str(device), "reason": "device not found"}

    try:
        from veristead.adapters import MockSQLiteAdapter, get_active_adapter
        adapter = get_active_adapter()
        if not isinstance(adapter, MockSQLiteAdapter) and hasattr(adapter, "simulate_offline"):
            return adapter.simulate_offline(device, offline)
    except Exception:
        pass

    with _connection() as conn:
        row, error_reason = _find_device(conn, device)
        if row is None:
            return {"status": "error", "device": device, "reason": error_reason}

        conn.execute(
            "UPDATE devices SET online = ? WHERE id = ?", (0 if offline else 1, row["id"])
        )

    return {"device": row["name"], "online": not offline}


def simulate_hardware_drift_impl(device: str, drift: bool = True) -> dict:
    """Demo/test tool: simulate silent physical hardware write failure or state drift.

    When drift is enabled for a device, physical hardware silently drops or corrupts
    mutating actions. The UPDATE is not reflected in hardware, so when Veristead's
    re-read verification step runs, it detects expected_state != actual_state,
    proving that re-reading is a true verification and reports status: 'failed'
    with reason: 'state verification failed'.
    """
    if not device or not isinstance(device, str):
        return {"status": "error", "device": str(device), "reason": "device not found"}

    try:
        from veristead.adapters import MockSQLiteAdapter, get_active_adapter
        adapter = get_active_adapter()
        if not isinstance(adapter, MockSQLiteAdapter) and hasattr(adapter, "simulate_hardware_drift"):
            return adapter.simulate_hardware_drift(device, drift)
    except Exception:
        pass

    with _connection() as conn:
        row, error_reason = _find_device(conn, device)
        if row is None:
            return {"status": "error", "device": device, "reason": error_reason}

        dev_id = row["id"]
        dev_name = row["name"].lower()

        if drift:
            _DRIFTED_DEVICES.add(dev_id)
            _DRIFTED_DEVICES.add(dev_name)
        else:
            _DRIFTED_DEVICES.discard(dev_id)
            _DRIFTED_DEVICES.discard(dev_name)

    return {
        "status": "ok",
        "device": row["name"],
        "drift": drift,
        "message": (
            f"Hardware write drift {'enabled' if drift else 'disabled'} for {row['name']}. "
            f"Subsequent actions will {'fail state verification' if drift else 'verify normally'}."
        ),
    }


def reset_hardware_drift() -> None:
    """Clear all simulated hardware drift flags."""
    _DRIFTED_DEVICES.clear()

