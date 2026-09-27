from veristead.tools import cards, devices, memory
from veristead.tools.security import (
    escalate_security_alert_impl,
    is_security_critical,
)


class _MockSNSClient:
    def __init__(self, message_id="sns-test-123", raise_exc=None):
        self.message_id = message_id
        self.raise_exc = raise_exc
        self.last_publish_kwargs = None

    def publish(self, **kwargs):
        self.last_publish_kwargs = kwargs
        if self.raise_exc:
            raise self.raise_exc
        return {"MessageId": self.message_id}


def _setup_db(tmp_path, monkeypatch):
    monkeypatch.setattr(devices, "DB_PATH", tmp_path / "devices.db")
    monkeypatch.setattr(memory, "DB_PATH", tmp_path / "memory.db")


def test_is_security_critical_identifies_locks_and_garage():
    assert is_security_critical("Front Door Lock", "lock") is True
    assert is_security_critical("Garage Door Opener", "garage") is True
    assert is_security_critical("Back Door Lock", "lock") is True
    assert is_security_critical("Kitchen Light", "light") is False
    assert is_security_critical("Thermostat", "thermostat") is False


def test_escalate_security_alert_simulated_without_topic_arn(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    monkeypatch.delenv("AWS_SNS_TOPIC_ARN", raising=False)

    result = escalate_security_alert_impl(
        device="Front Door Lock",
        reason="device is offline",
        routine="good night",
    )

    assert result["status"] == "simulated"
    assert result["channel"] == "sns"
    assert result["severity"] == "CRITICAL"
    assert result["device"] == "Front Door Lock"
    assert result["dispatched"] is False
    assert result["message_id"].startswith("sim-sns-")
    assert "CRITICAL SECURITY ALERT" in result["alert"]["message"]
    assert result["alert"]["routine"] == "good night"


def test_escalate_security_alert_dispatches_with_live_client(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    monkeypatch.setenv("AWS_SNS_TOPIC_ARN", "arn:aws:sns:us-east-1:123456789012:test-topic")

    mock_client = _MockSNSClient(message_id="msg-abc-999")
    result = escalate_security_alert_impl(
        device="Front Door Lock",
        reason="state verification failed",
        routine="good night",
        client=mock_client,
    )

    assert result["status"] == "escalated"
    assert result["dispatched"] is True
    assert result["message_id"] == "msg-abc-999"
    assert mock_client.last_publish_kwargs is not None
    assert mock_client.last_publish_kwargs["TopicArn"] == "arn:aws:sns:us-east-1:123456789012:test-topic"
    assert "CRITICAL SECURITY ALERT" in mock_client.last_publish_kwargs["Subject"]


def test_escalate_security_alert_handles_sns_exception_gracefully(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    monkeypatch.setenv("AWS_SNS_TOPIC_ARN", "arn:aws:sns:us-east-1:123456789012:test-topic")

    mock_client = _MockSNSClient(raise_exc=RuntimeError("SNS service unavailable"))
    result = escalate_security_alert_impl(
        device="Garage Door Opener",
        reason="failed to close",
        routine="good night",
        client=mock_client,
    )

    assert result["status"] == "escalation_error"
    assert result["severity"] == "CRITICAL"
    assert "SNS service unavailable" in result["reason"]


def test_escalate_security_alert_persists_to_memory(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)

    escalate_security_alert_impl("Front Door Lock", "device is offline")

    entries = memory.recall_context_impl("security:escalation")
    assert len(entries) > 0
    assert "Front Door Lock" in entries[0]["detail"]


def test_good_night_triggers_sns_escalation_when_front_door_lock_fails(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    devices.simulate_offline_device_impl("Front Door Lock", offline=True)

    result = devices.run_routine_impl("good night")

    assert result["status"] == "partial_failure"
    assert len(result["security_alerts"]) >= 1
    alert = next(a for a in result["security_alerts"] if a["device"] == "Front Door Lock")
    assert alert["severity"] == "CRITICAL"


def test_good_night_triggers_sns_escalation_when_back_door_lock_fails(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    devices.simulate_offline_device_impl("Back Door Lock", offline=True)

    result = devices.run_routine_impl("good night")

    assert result["status"] == "partial_failure"
    assert len(result["security_alerts"]) >= 1
    alert = next(a for a in result["security_alerts"] if a["device"] == "Back Door Lock")
    assert alert["severity"] == "CRITICAL"


def test_non_security_failure_does_not_trigger_sns_escalation(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    devices.simulate_offline_device_impl("Kitchen Light", offline=True)

    result = devices.run_routine_impl("good night")

    assert result["status"] == "partial_failure"
    assert len(result["security_alerts"]) == 0


def test_routine_card_renders_security_escalation_section():
    result = {
        "status": "partial_failure",
        "routine": "good night",
        "summary": "6 succeeded, 1 failed (Front Door Lock)",
        "results": [
            {"status": "failed", "device": "Front Door Lock", "reason": "device is offline"},
        ],
        "security_alerts": [
            {
                "status": "escalated",
                "channel": "sns",
                "severity": "CRITICAL",
                "device": "Front Door Lock",
                "message_id": "sns-alert-5678",
            }
        ],
    }

    card = cards.format_routine_result_card(result)

    assert "🚨 Critical Security Escalations (AWS SNS)" in card
    assert "Front Door Lock" in card
    assert "CRITICAL" in card
    assert "sns-alert-5678" in card


def test_alerts_module_exports_and_functionality(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    import veristead.tools.alerts as alerts
    assert hasattr(alerts, "escalate_security_alert_impl")
    assert hasattr(alerts, "is_security_critical")
    assert alerts.is_security_critical("Front Door Lock") is True
    assert alerts.is_security_critical("Kitchen Light") is False

    res = alerts.escalate_security_alert_impl(
        device="Garage Door Opener",
        reason="failed to close",
    )
    assert res["status"] == "simulated"
    assert res["device"] == "Garage Door Opener"
    assert res["alert"]["routine"] == "manual_command"


def test_escalate_security_alert_null_inputs(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)

    res = escalate_security_alert_impl(None, None)
    assert res["status"] == "simulated"
    assert res["device"] == "Unknown Device"
    assert "security check failed" in res["alert"]["reason"]


def test_is_security_critical_with_none_or_explicit_dtype():
    assert is_security_critical(None) is False
    assert is_security_critical(None, dtype="lock") is True
    assert is_security_critical("Main Entrance", dtype="lock") is True
