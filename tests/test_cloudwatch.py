"""Tests for AWS CloudWatch Logs audit trail and cryptographic execution receipts."""
import json
from unittest.mock import MagicMock

import pytest

from veristead.tools import cloudwatch, devices


@pytest.fixture(autouse=True)
def clean_audit_and_drift(tmp_path, monkeypatch):
    monkeypatch.setattr(cloudwatch, "DB_PATH", tmp_path / "audit.db")
    monkeypatch.setattr(devices, "DB_PATH", tmp_path / "devices.db")
    cloudwatch.reset_audit_trail()
    devices.reset_hardware_drift()
    yield
    cloudwatch.reset_audit_trail()
    devices.reset_hardware_drift()


def test_log_execution_receipt_creates_cryptographic_chain():
    """Consecutive execution receipts form an unbroken SHA-256 hash chain."""
    r1 = cloudwatch.log_execution_receipt(
        device="Kitchen Light",
        action="on",
        status="success",
        expected_state={"power": "on"},
        actual_state={"power": "on"},
    )
    assert r1["receipt_id"].startswith("rcpt-")
    assert r1["previous_hash"] == "0" * 64
    assert len(r1["signature_hash"]) == 64
    assert cloudwatch.verify_audit_receipt(r1) is True

    r2 = cloudwatch.log_execution_receipt(
        device="Thermostat",
        action="set:22",
        status="success",
        expected_state={"temperature": 22},
        actual_state={"temperature": 22},
    )
    assert r2["previous_hash"] == r1["signature_hash"]
    assert len(r2["signature_hash"]) == 64
    assert cloudwatch.verify_audit_receipt(r2) is True


def test_tampered_receipt_fails_verification():
    """Tampering with any field invalidates the cryptographic receipt signature."""
    receipt = cloudwatch.log_execution_receipt(
        device="Front Door Lock",
        action="lock",
        status="success",
        expected_state={"locked": True},
        actual_state={"locked": True},
    )
    assert cloudwatch.verify_audit_receipt(receipt) is True

    # Tamper with status or actual state
    tampered = dict(receipt)
    tampered["status"] = "failed"
    assert cloudwatch.verify_audit_receipt(tampered) is False

    tampered_state = dict(receipt)
    tampered_state["actual_state"] = {"locked": False}
    assert cloudwatch.verify_audit_receipt(tampered_state) is False


def test_get_execution_audit_trail_returns_recent_receipts():
    """get_execution_audit_trail_impl returns receipts in reverse chronological order."""
    cloudwatch.log_execution_receipt("Device 1", "on", "success")
    cloudwatch.log_execution_receipt("Device 2", "off", "success")
    cloudwatch.log_execution_receipt("Device 3", "lock", "success")

    trail = cloudwatch.get_execution_audit_trail_impl(limit=2)
    assert len(trail) == 2
    assert trail[0]["device"] == "Device 3"
    assert trail[1]["device"] == "Device 2"
    assert all(r["verified"] is True for r in trail)


def test_execute_device_action_automatically_generates_audit_receipt():
    """Every verified action call automatically logs an execution receipt."""
    cloudwatch.reset_audit_trail()
    res = devices.execute_device_action_impl("Kitchen Light", "on")
    assert res["status"] == "success"

    trail = cloudwatch.get_execution_audit_trail_impl(limit=5)
    assert len(trail) >= 1
    latest = trail[0]
    assert latest["device"] == "Kitchen Light"
    assert latest["action"] == "on"
    assert latest["status"] == "success"
    assert latest["verified"] is True


def test_hardware_drift_failure_logged_to_audit_receipt():
    """When hardware drift occurs, the verification failure receipt is recorded with full diagnostics."""
    cloudwatch.reset_audit_trail()
    devices.simulate_hardware_drift_impl("Kitchen Light", True)

    res = devices.execute_device_action_impl("Kitchen Light", "on")
    assert res["status"] == "failed"

    trail = cloudwatch.get_execution_audit_trail_impl(limit=5)
    assert len(trail) >= 1
    latest = trail[0]
    assert latest["device"] == "Kitchen Light"
    assert latest["status"] == "failed"
    assert latest["expected_state"] == {"power": "on"}
    assert latest["actual_state"] == {"power": "off"}
    assert latest["verified"] is True


def test_cloudwatch_client_mock_dispatch():
    """When AWS client is provided, receipt is dispatched via put_log_events."""
    mock_client = MagicMock()
    mock_client.put_log_events.return_value = {"nextSequenceToken": "tok_123"}

    receipt = cloudwatch.log_execution_receipt(
        device="Back Door Lock",
        action="lock",
        status="success",
        client=mock_client,
    )
    assert receipt["dispatched"] is True
    mock_client.put_log_events.assert_called_once()
    call_kwargs = mock_client.put_log_events.call_args[1]
    assert "logGroupName" in call_kwargs
    assert "logEvents" in call_kwargs


def test_cloudwatch_client_handles_resource_not_found():
    """When log group/stream is missing, client creates them and retries."""
    class ResourceNotFoundException(Exception):
        pass

    mock_client = MagicMock()
    mock_client.put_log_events.side_effect = [
        ResourceNotFoundException("Log group does not exist"),
        {"nextSequenceToken": "tok_123"},
    ]

    receipt = cloudwatch.log_execution_receipt(
        device="Office Desk Lamp",
        action="off",
        status="success",
        client=mock_client,
    )
    assert receipt["dispatched"] is True
    assert mock_client.create_log_group.called
    assert mock_client.create_log_stream.called
    assert mock_client.put_log_events.call_count == 2
