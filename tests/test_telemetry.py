"""Unit tests for Veristead Verification Telemetry & Impact Engine (Pillars 1, 2, 7).

Tests action tracking, silent routine failure prevention benchmarking (18.4% baseline),
self-healing compensation logging, security escalation tracking, and visual card rendering.
"""
from __future__ import annotations

from pathlib import Path
from veristead.tools import cards, devices, memory, telemetry


def _setup_telemetry_db(tmp_path, monkeypatch):
    monkeypatch.setattr(devices, "DB_PATH", tmp_path / "devices.db")
    monkeypatch.setattr(memory, "DB_PATH", tmp_path / "memory.db")
    monkeypatch.setattr(telemetry, "DB_PATH", tmp_path / "telemetry.db")
    telemetry.reset_telemetry_impl()


def test_record_action_success_and_metrics(tmp_path, monkeypatch):
    _setup_telemetry_db(tmp_path, monkeypatch)

    telemetry.record_action_result("Kitchen Light", "on", "success")

    metrics = telemetry.get_reliability_metrics_impl()
    assert metrics["status"] == "ok"
    assert metrics["total_actions"] == 1
    assert metrics["verified_successes"] == 1
    assert metrics["verification_failures"] == 0
    assert metrics["silent_failures_prevented"] == 0
    assert metrics["verification_pass_rate_pct"] == 100.0


def test_record_action_failure_increments_silent_failure_prevented(tmp_path, monkeypatch):
    _setup_telemetry_db(tmp_path, monkeypatch)

    # In unverified systems, an action on an offline device returns a blind "Okay".
    # Veristead catches and prevents this silent failure.
    telemetry.record_action_result("Kitchen Light", "on", "failed", "device is offline")

    metrics = telemetry.get_reliability_metrics_impl()
    assert metrics["total_actions"] == 1
    assert metrics["verified_successes"] == 0
    assert metrics["verification_failures"] == 1
    assert metrics["silent_failures_prevented"] == 1
    assert metrics["verification_pass_rate_pct"] == 0.0
    assert "1 silent routine failures" in metrics["benchmark_summary"]


def test_record_compensation_and_security_escalation(tmp_path, monkeypatch):
    _setup_telemetry_db(tmp_path, monkeypatch)

    telemetry.record_compensation(
        failed_device="Kitchen Light",
        substitute_device="Living Room Light",
        compensating_action="off",
        status="success",
    )
    telemetry.record_security_escalation(
        device="Front Door Lock",
        severity="CRITICAL",
        reason="device is offline",
        routine="good night",
    )

    metrics = telemetry.get_reliability_metrics_impl()
    assert metrics["compensations_executed"] == 1
    assert metrics["security_escalations_dispatched"] == 1


def test_record_routine(tmp_path, monkeypatch):
    _setup_telemetry_db(tmp_path, monkeypatch)

    telemetry.record_routine(
        routine_name="good night",
        status="partial_failure",
        step_count=7,
        failed_count=1,
    )

    metrics = telemetry.get_reliability_metrics_impl()
    assert metrics["routines_executed"] == 1


def test_industry_benchmark_and_mtbf_computation(tmp_path, monkeypatch):
    _setup_telemetry_db(tmp_path, monkeypatch)

    # Simulate 8 successes and 2 failures
    for i in range(8):
        telemetry.record_action_result(f"Device_{i}", "off", "success")
    for j in range(2):
        telemetry.record_action_result(f"FailedDevice_{j}", "lock", "failed", "device offline")

    metrics = telemetry.get_reliability_metrics_impl()
    assert metrics["total_actions"] == 10
    assert metrics["verified_successes"] == 8
    assert metrics["verification_failures"] == 2
    assert metrics["verification_pass_rate_pct"] == 80.0
    assert metrics["silent_failures_prevented"] == 2
    assert metrics["industry_unverified_failure_rate_pct"] == 18.4
    assert metrics["false_positive_confirmations"] == 0
    assert metrics["false_positive_prevention_rate_pct"] == 100.0
    assert metrics["mean_actions_between_failures"] == 5.0  # 10 / 2 = 5.0 actions


def test_reset_telemetry(tmp_path, monkeypatch):
    _setup_telemetry_db(tmp_path, monkeypatch)

    telemetry.record_action_result("Light", "on", "success")
    assert telemetry.get_reliability_metrics_impl()["total_actions"] == 1

    telemetry.reset_telemetry_impl()
    assert telemetry.get_reliability_metrics_impl()["total_actions"] == 0


def test_format_telemetry_card():
    sample_metrics = {
        "status": "ok",
        "total_actions": 25,
        "verified_successes": 23,
        "verification_failures": 2,
        "silent_failures_prevented": 2,
        "verification_pass_rate_pct": 92.0,
        "industry_unverified_failure_rate_pct": 18.4,
        "mean_actions_between_failures": 12.5,
        "compensations_executed": 2,
        "security_escalations_dispatched": 1,
        "benchmark_summary": "Prevented 2 silent routine failures.",
    }

    card = cards.format_telemetry_card(sample_metrics)
    assert "Veristead Reliability & Impact Telemetry" in card
    assert "25" in card
    assert "92.0%" in card
    assert "18.4%" in card
    assert "12.5 actions" in card
    assert "- **Self-Healing Compensations Executed:** 2" in card
    assert "- **Critical Security Escalations (AWS SNS):** 1" in card


def test_device_execution_automatically_records_telemetry(tmp_path, monkeypatch):
    _setup_telemetry_db(tmp_path, monkeypatch)

    devices.execute_device_action_impl("Kitchen Light", "on")

    metrics = telemetry.get_reliability_metrics_impl()
    assert metrics["total_actions"] == 1
    assert metrics["verified_successes"] == 1


def test_routine_execution_automatically_records_telemetry(tmp_path, monkeypatch):
    _setup_telemetry_db(tmp_path, monkeypatch)

    # Take Kitchen Light offline to trigger partial failure, compensation, and telemetry
    devices.simulate_offline_device_impl("Kitchen Light", offline=True)
    res = devices.run_routine_impl("good night")

    assert res["status"] == "partial_failure"
    metrics = telemetry.get_reliability_metrics_impl()
    assert metrics["routines_executed"] == 1
    assert metrics["total_actions"] >= 7
    assert metrics["silent_failures_prevented"] >= 1
    assert metrics["compensations_executed"] >= 1


def test_telemetry_resilience_to_errors(monkeypatch):
    import sqlite3

    def _mock_connect(*args, **kwargs):
        raise sqlite3.OperationalError("database locked or unavailable")

    monkeypatch.setattr(sqlite3, "connect", _mock_connect)

    # Ensure telemetry calls gracefully catch exceptions without raising
    # Should not raise exception
    telemetry.record_action_result("Device", "on", "success")
    telemetry.record_compensation("D1", "D2", "off", "success")
    telemetry.record_security_escalation("D1", "CRITICAL", "offline")
    telemetry.record_routine("routine", "ok", 1, 0)
    telemetry.reset_telemetry_impl()

    # get_reliability_metrics_impl returns graceful fallback error dict instead of crashing
    metrics = telemetry.get_reliability_metrics_impl()
    assert metrics["status"] == "error"
    assert "reason" in metrics
    assert metrics["total_actions"] == 0


def test_zero_actions_metrics(tmp_path, monkeypatch):
    _setup_telemetry_db(tmp_path, monkeypatch)
    metrics = telemetry.get_reliability_metrics_impl()
    assert metrics["total_actions"] == 0
    assert metrics["total_verified_executions"] == 0
    assert metrics["verification_pass_rate_pct"] == 100.0
    assert metrics["verification_success_rate_pct"] == 100.0
    assert metrics["routine_partial_failure_rate_pct"] == 0.0
    assert metrics["autonomous_self_healing_recovery_rate_pct"] == 100.0
    assert metrics["security_escalation_count"] == 0
    assert metrics["mean_actions_between_failures"] == 0.0
    assert metrics["silent_failures_prevented"] == 0


def test_real_time_household_reliability_metrics(tmp_path, monkeypatch):
    _setup_telemetry_db(tmp_path, monkeypatch)

    # 4 successful actions and 1 failed action
    for i in range(4):
        telemetry.record_action_result(f"Light_{i}", "off", "success")
    telemetry.record_action_result("Front Door Lock", "lock", "failed", "device offline")

    # 1 routine with partial failure, 1 routine with success
    telemetry.record_routine("good night", "partial_failure", step_count=7, failed_count=1)
    telemetry.record_routine("good morning", "ok", step_count=2, failed_count=0)

    # 1 successful compensation and 1 security escalation
    telemetry.record_compensation("Kitchen Light", "Living Room Light", "off", "success")
    telemetry.record_security_escalation("Front Door Lock", "CRITICAL", "device is offline", "good night")

    metrics = telemetry.get_verification_telemetry_impl()
    assert metrics["status"] == "ok"
    assert metrics["total_verified_executions"] == 5
    assert metrics["verified_successes"] == 4
    assert metrics["verification_failures"] == 1
    assert metrics["verification_success_rate_pct"] == 80.0
    assert metrics["silent_failures_prevented"] == 1
    assert metrics["routines_executed"] == 2
    assert metrics["routine_partial_failure_rate_pct"] == 50.0  # 1 out of 2 routines was partial_failure
    assert metrics["autonomous_self_healing_recovery_rate_pct"] == 100.0
    assert metrics["security_escalation_count"] == 1
    assert metrics["security_escalations_dispatched"] == 1
    assert "18–24%" in metrics["benchmark_summary"]


def test_autonomous_self_healing_recovery_rate_calculation(tmp_path, monkeypatch):
    _setup_telemetry_db(tmp_path, monkeypatch)

    # Record 1 successful compensation and 1 failed compensation
    telemetry.record_compensation("Kitchen Light", "Living Room Light", "off", "success")
    telemetry.record_compensation("Front Door Lock", "Back Door Lock", "lock", "failed")

    metrics = telemetry.get_reliability_metrics_impl()
    # 1 success out of 2 attempted = 50.0%
    assert metrics["autonomous_self_healing_recovery_rate_pct"] == 50.0
    assert metrics["compensations_executed"] == 1


