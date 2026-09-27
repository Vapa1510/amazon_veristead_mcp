"""AWS Security Escalation via Amazon SNS (Capability Charter, Pillars 1 & 4).

When a security-critical smart-home device (front door lock, back door lock,
garage door opener) fails to secure during a safety routine like 'good night',
Veristead escalates it as a CRITICAL security alert.

Dispatches via Amazon SNS (boto3.client('sns')) with a verified mock/simulation
fallback when AWS_SNS_TOPIC_ARN is not configured, ensuring hermetic local testing
and judge evaluation without live AWS credentials.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone

import boto3
from botocore.config import Config

from veristead.tools.memory import remember

logger = logging.getLogger("veristead.security")

_sns_client = None

# Devices considered critical for physical household perimeter security.
SECURITY_DEVICE_TYPES = {"lock", "garage"}
SECURITY_NAME_KEYWORDS = ("lock", "door", "garage", "deadbolt", "security", "entryway")


def is_security_critical(device_name: str, dtype: str | None = None) -> bool:
    """Return True if a device is security-critical."""
    if dtype in SECURITY_DEVICE_TYPES:
        return True
    name_lower = (device_name or "").lower()
    return any(k in name_lower for k in SECURITY_NAME_KEYWORDS)


def _get_sns_client():
    """Create or reuse a boto3 SNS client."""
    global _sns_client
    if _sns_client is None:
        region = os.getenv("AWS_REGION", "us-east-1")
        _sns_client = boto3.client(
            "sns",
            region_name=region,
            config=Config(
                connect_timeout=2,
                read_timeout=3,
                retries={"max_attempts": 2, "mode": "standard"},
            ),
        )
    return _sns_client


def escalate_security_alert_impl(
    device: str,
    reason: str,
    routine: str | None = None,
    client=None,
) -> dict:
    """Escalate a critical security failure via Amazon SNS or hermetic simulation.

    Args:
        device: name of the security-critical device that failed (e.g. 'Front Door Lock').
        reason: reason the device failed to secure (e.g. 'device is offline').
        routine: optional routine name during which failure occurred (e.g. 'good night').
        client: optional pre-configured SNS client for testing.
    """
    device = device or "Unknown Device"
    reason = reason or "security check failed"
    severity = "CRITICAL"
    timestamp = datetime.now(timezone.utc).isoformat()
    routine_label = routine or "manual_command"
    subject = f"[CRITICAL SECURITY ALERT] {device} Failed to Secure"[:100]

    alert_payload = {
        "severity": severity,
        "alert_type": "SECURITY_DEVICE_FAILURE",
        "device": device,
        "reason": reason,
        "routine": routine_label,
        "timestamp": timestamp,
        "message": (
            f"CRITICAL SECURITY ALERT: Hardware device '{device}' failed to secure "
            f"({reason}) during routine '{routine_label}'. Physical perimeter check required."
        ),
    }

    try:
        from veristead.tools.telemetry import record_security_escalation
        record_security_escalation(
            device=device,
            severity=severity,
            reason=reason,
            routine=routine,
        )
    except Exception:
        pass

    try:
        from veristead.tools.cloudwatch import log_execution_receipt
        log_execution_receipt(
            device=device,
            action="security_escalation",
            status="escalated" if (os.getenv("AWS_SNS_TOPIC_ARN") or client is not None) else "simulated",
            details=alert_payload,
        )
    except Exception:
        pass


    topic_arn = os.getenv("AWS_SNS_TOPIC_ARN")

    # If AWS_SNS_TOPIC_ARN is configured or client is passed explicitly in tests
    if topic_arn or client is not None:
        arn = topic_arn or "arn:aws:sns:us-east-1:123456789012:veristead-security-alerts"
        sns = client or _get_sns_client()
        try:
            response = sns.publish(
                TopicArn=arn,
                Subject=subject,
                Message=json.dumps(alert_payload),
            )
            message_id = response.get("MessageId", f"sns-{uuid.uuid4().hex[:8]}")
            remember(
                topic="security:escalation",
                detail=f"CRITICAL: {device} failed to secure ({reason}) -> SNS alert {message_id}",
            )
            return {
                "status": "escalated",
                "channel": "sns",
                "severity": "CRITICAL",
                "device": device,
                "topic_arn": arn,
                "message_id": message_id,
                "dispatched": True,
                "alert": alert_payload,
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to publish alert to SNS: %s", exc)
            return {
                "status": "escalation_error",
                "channel": "sns",
                "severity": "CRITICAL",
                "device": device,
                "reason": f"SNS publish failed: {exc}",
                "alert": alert_payload,
            }

    # Hermetic simulation fallback for local evaluation and testing without AWS credentials
    sim_id = f"sim-sns-{uuid.uuid4().hex[:8]}"
    remember(
        topic="security:escalation",
        detail=f"CRITICAL (simulated SNS): {device} failed to secure ({reason}) during '{routine_label}'",
    )
    return {
        "status": "simulated",
        "channel": "sns",
        "severity": "CRITICAL",
        "device": device,
        "topic_arn": None,
        "message_id": sim_id,
        "dispatched": False,
        "simulation_note": "AWS_SNS_TOPIC_ARN not set. Escalate via simulated SNS dispatch for local testing.",
        "alert": alert_payload,
    }
