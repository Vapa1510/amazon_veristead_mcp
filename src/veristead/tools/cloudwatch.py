"""AWS CloudWatch Logs Audit Trail & Cryptographic Execution Receipts (Capability Charter, Pillars 1, 4, 6).

Every mutating device action, state verification check, and critical security escalation
generates a cryptographically chained, tamper-evident execution receipt.

Receipts are logged to AWS CloudWatch Logs (boto3.client('logs')) with structured JSON
and SHA-256 integrity signatures, with hermetic local ledger simulation fallback when
AWS credentials or CLOUDWATCH log groups are not configured.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config

from veristead.tools.memory import remember

logger = logging.getLogger("veristead.cloudwatch")

DB_PATH = Path(__file__).resolve().parents[3] / "data" / "audit.db"

_cloudwatch_client = None
_AUDIT_LEDGER: list[dict] = []
_GENESIS_HASH = "0" * 64


def _get_cloudwatch_client():
    """Create or reuse a boto3 CloudWatch Logs client with hardened timeouts."""
    global _cloudwatch_client
    if _cloudwatch_client is None:
        region = os.getenv("AWS_REGION", "us-east-1")
        _cloudwatch_client = boto3.client(
            "logs",
            region_name=region,
            config=Config(
                connect_timeout=2,
                read_timeout=3,
                retries={"max_attempts": 2, "mode": "standard"},
            ),
        )
    return _cloudwatch_client


def _compute_receipt_hash(payload: dict, prev_hash: str) -> str:
    """Compute deterministic SHA-256 hash for cryptographic receipt chain."""
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    content = f"{serialized}:{prev_hash}".encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def verify_audit_receipt(receipt: dict) -> bool:
    """Cryptographically verify the integrity signature of an audit receipt."""
    if not isinstance(receipt, dict):
        return False
    signature_hash = receipt.get("signature_hash")
    if not signature_hash:
        return False

    prev_hash = receipt.get("previous_hash", _GENESIS_HASH)
    payload_to_verify = {
        "receipt_id": receipt.get("receipt_id"),
        "timestamp": receipt.get("timestamp"),
        "device": receipt.get("device"),
        "action": receipt.get("action"),
        "status": receipt.get("status"),
        "expected_state": receipt.get("expected_state"),
        "actual_state": receipt.get("actual_state"),
        "details": receipt.get("details", {}),
    }
    recalculated = _compute_receipt_hash(payload_to_verify, prev_hash)
    return recalculated == signature_hash


def _ensure_audit_db() -> sqlite3.Connection | None:
    """Ensure SQLite table exists for local audit persistence."""
    try:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(DB_PATH, timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_receipts (
                receipt_id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                device TEXT NOT NULL,
                action TEXT NOT NULL,
                status TEXT NOT NULL,
                signature_hash TEXT NOT NULL,
                previous_hash TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )
        conn.commit()
        return conn
    except Exception as exc:
        logger.debug("Local audit DB unavailable, using in-memory ledger: %s", exc)
        return None


def reset_audit_trail() -> None:
    """Hermetic reset helper for test suites."""
    global _AUDIT_LEDGER
    _AUDIT_LEDGER.clear()
    try:
        if DB_PATH.exists():
            DB_PATH.unlink()
    except Exception:
        pass


def log_execution_receipt(
    device: str,
    action: str,
    status: str,
    expected_state: dict | None = None,
    actual_state: dict | None = None,
    details: dict | None = None,
    client: Any = None,
) -> dict:
    """Record a cryptographically verifiable execution receipt to AWS CloudWatch Logs.

    Falls back cleanly to hermetic in-memory & SQLite audit ledger when AWS
    CloudWatch is unavailable or running without credentials.

    Args:
        device: Name of the smart-home device (e.g. "Kitchen Light").
        action: Action attempted/executed (e.g. "on", "set:22").
        status: "success", "failed", "error", or "escalated".
        expected_state: Target state post-action.
        actual_state: Re-read state after verification.
        details: Optional additional metadata (e.g. routine name, security alerts).
        client: Optional pre-configured boto3 logs client for unit testing.
    """
    global _AUDIT_LEDGER

    now_utc = datetime.now(timezone.utc)
    timestamp_str = now_utc.isoformat()
    receipt_id = f"rcpt-{uuid.uuid4().hex[:12]}"

    prev_hash = _AUDIT_LEDGER[-1]["signature_hash"] if _AUDIT_LEDGER else _GENESIS_HASH

    payload = {
        "receipt_id": receipt_id,
        "timestamp": timestamp_str,
        "device": device or "unknown",
        "action": action or "unknown",
        "status": status or "unknown",
        "expected_state": expected_state,
        "actual_state": actual_state,
        "details": details or {},
    }

    sig_hash = _compute_receipt_hash(payload, prev_hash)

    log_group = os.getenv("AWS_CLOUDWATCH_LOG_GROUP", "/veristead/execution-audit")
    log_stream = os.getenv("AWS_CLOUDWATCH_LOG_STREAM", f"audit-{now_utc.strftime('%Y-%m-%d')}")

    receipt: dict[str, Any] = {
        **payload,
        "previous_hash": prev_hash,
        "signature_hash": sig_hash,
        "channel": "cloudwatch",
        "log_group": log_group,
        "log_stream": log_stream,
        "dispatched": False,
        "verified": True,
    }

    # Record to local in-memory ledger
    _AUDIT_LEDGER.append(receipt)

    # Persist to local SQLite ledger
    conn = _ensure_audit_db()
    if conn is not None:
        try:
            with conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO audit_receipts
                    (receipt_id, timestamp, device, action, status, signature_hash, previous_hash, payload_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        receipt_id,
                        timestamp_str,
                        device or "unknown",
                        action or "unknown",
                        status or "unknown",
                        sig_hash,
                        prev_hash,
                        json.dumps(receipt),
                    ),
                )
        except Exception as exc:
            logger.debug("Failed writing to audit sqlite table: %s", exc)
        finally:
            conn.close()

    # Dispatch to AWS CloudWatch Logs if client or AWS_CLOUDWATCH_LOG_GROUP is active
    is_live_aws = bool(os.getenv("AWS_CLOUDWATCH_LOG_GROUP") or os.getenv("AWS_ACCESS_KEY_ID") or client)
    if is_live_aws or client is not None:
        cw_client = client or _get_cloudwatch_client()
        event_time_ms = int(now_utc.timestamp() * 1000)
        try:
            cw_client.put_log_events(
                logGroupName=log_group,
                logStreamName=log_stream,
                logEvents=[
                    {
                        "timestamp": event_time_ms,
                        "message": json.dumps(receipt),
                    }
                ],
            )
            receipt["dispatched"] = True
        except Exception as exc:
            err_name = exc.__class__.__name__
            # If log group or stream missing, attempt creation once
            if "ResourceNotFoundException" in err_name:
                try:
                    cw_client.create_log_group(logGroupName=log_group)
                except Exception:
                    pass
                try:
                    cw_client.create_log_stream(logGroupName=log_group, logStreamName=log_stream)
                except Exception:
                    pass
                try:
                    cw_client.put_log_events(
                        logGroupName=log_group,
                        logStreamName=log_stream,
                        logEvents=[{"timestamp": event_time_ms, "message": json.dumps(receipt)}],
                    )
                    receipt["dispatched"] = True
                except Exception as retry_exc:
                    receipt["dispatched"] = False
                    receipt["cloudwatch_error"] = str(retry_exc)
            else:
                receipt["dispatched"] = False
                receipt["cloudwatch_error"] = str(exc)

    # Record hash receipt in Veristead memory
    remember(
        topic="audit:cloudwatch",
        detail=f"Audit receipt {receipt_id} [{status}] {device}:{action} hash={sig_hash[:12]}... (cw={receipt['dispatched']})",
    )

    return receipt


def get_execution_audit_trail_impl(limit: int = 10, client: Any = None) -> list[dict]:
    """Retrieve verified execution audit trail from CloudWatch / local ledger.

    Returns the most recent `limit` audit receipts in reverse chronological order.
    Each receipt includes cryptographic hash verification status.

    Args:
        limit: Maximum number of audit receipts to return (default: 10).
        client: Optional boto3 CloudWatch Logs client for test mocking.
    """
    limit = max(1, min(limit, 100))

    # If client passed with mock filter_log_events, retrieve from client
    if client is not None and hasattr(client, "filter_log_events"):
        try:
            res = client.filter_log_events(
                logGroupName=os.getenv("AWS_CLOUDWATCH_LOG_GROUP", "/veristead/execution-audit"),
                limit=limit,
            )
            events = res.get("events", [])
            trail = []
            for ev in events:
                try:
                    parsed = json.loads(ev.get("message", "{}"))
                    parsed["verified"] = verify_audit_receipt(parsed)
                    trail.append(parsed)
                except Exception:
                    continue
            if trail:
                return sorted(trail, key=lambda x: x.get("timestamp", ""), reverse=True)[:limit]
        except Exception as exc:
            logger.debug("Failed reading from client filter_log_events: %s", exc)

    # Read from local in-memory ledger if populated
    if _AUDIT_LEDGER:
        trail = []
        for r in reversed(_AUDIT_LEDGER[-limit:]):
            item = dict(r)
            item["verified"] = verify_audit_receipt(item)
            trail.append(item)
        return trail

    # Fallback to local SQLite audit DB
    conn = _ensure_audit_db()
    if conn is not None:
        try:
            with conn:
                rows = conn.execute(
                    "SELECT payload_json FROM audit_receipts ORDER BY rowid DESC LIMIT ?",
                    (limit,),
                ).fetchall()
                trail = []
                for row in rows:
                    parsed = json.loads(row[0])
                    parsed["verified"] = verify_audit_receipt(parsed)
                    trail.append(parsed)
                return trail
        except Exception as exc:
            logger.debug("Failed reading from audit sqlite table: %s", exc)
        finally:
            conn.close()

    return []
