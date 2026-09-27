"""Audit logging alias module for CloudWatch execution receipts."""
from __future__ import annotations

from veristead.tools.cloudwatch import (
    _get_cloudwatch_client,
    get_execution_audit_trail_impl,
    log_execution_receipt,
    reset_audit_trail,
    verify_audit_receipt,
)

__all__ = [
    "_get_cloudwatch_client",
    "get_execution_audit_trail_impl",
    "log_execution_receipt",
    "reset_audit_trail",
    "verify_audit_receipt",
]
