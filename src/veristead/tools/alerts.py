"""AWS Security Escalation via Amazon SNS (Capability Charter, Pillars 1 & 4).

When a security-critical smart-home device (front door lock, back door lock,
garage door opener) fails to secure during a safety routine like 'good night',
Veristead escalates it as a CRITICAL security alert.

Dispatches via Amazon SNS (boto3.client('sns')) with a verified mock/simulation
fallback when AWS_SNS_TOPIC_ARN is not configured, ensuring hermetic local testing
and judge evaluation without live AWS credentials.
"""
from __future__ import annotations

from veristead.tools.security import (
    SECURITY_DEVICE_TYPES,
    SECURITY_NAME_KEYWORDS,
    _get_sns_client,
    escalate_security_alert_impl,
    is_security_critical,
)

__all__ = [
    "SECURITY_DEVICE_TYPES",
    "SECURITY_NAME_KEYWORDS",
    "_get_sns_client",
    "escalate_security_alert_impl",
    "is_security_critical",
]
