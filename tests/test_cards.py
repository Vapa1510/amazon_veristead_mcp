"""Tests for visual confirmation card formatters."""
from __future__ import annotations

from veristead.tools.cards import (
    RichCard,
    format_adapter_status_card,
    format_device_status_card,
    format_proposal_card,
    format_proposal_execution_card,
    format_replenishment_card,
    format_routine_result_card,
    format_security_alert_card,
    format_telemetry_card,
)


def test_device_status_card_groups_by_room():
    devices = [
        {"name": "Living Room Light", "room": "living room", "type": "light", "state": {"power": "on"}, "online": True},
        {"name": "Thermostat", "room": "living room", "type": "thermostat", "state": {"temperature": 21}, "online": True},
        {"name": "Kitchen Light", "room": "kitchen", "type": "light", "state": {"power": "off"}, "online": False},
    ]

    card = format_device_status_card(devices)

    assert "Smart Home Dashboard" in card
    assert "Living Room" in card
    assert "Kitchen" in card
    assert "Living Room Light" in card
    assert "🟢" in card  # online indicator
    assert "🔴" in card  # offline indicator


def test_device_status_card_empty():
    card = format_device_status_card([])
    assert "No devices found" in card


def test_routine_result_card_success():
    result = {
        "status": "ok",
        "routine": "movie time",
        "summary": "3 succeeded, 0 failed",
        "results": [
            {"status": "success", "device": "Living Room Light", "new_state": {"power": "off"}},
            {"status": "success", "device": "Office Desk Lamp", "new_state": {"power": "off"}},
            {"status": "success", "device": "Thermostat", "new_state": {"temperature": 20}},
        ],
    }

    card = format_routine_result_card(result)

    assert "✅" in card
    assert "Movie Time" in card
    assert "Living Room Light" in card
    assert "3 succeeded" in card


def test_routine_result_card_partial_failure():
    result = {
        "status": "partial_failure",
        "routine": "good night",
        "summary": "6 succeeded, 1 failed (Kitchen Light)",
        "results": [
            {"status": "success", "device": "Living Room Light", "new_state": {"power": "off"}},
            {"status": "failed", "device": "Kitchen Light", "reason": "device is offline"},
        ],
    }

    card = format_routine_result_card(result)

    assert "⚠️" in card
    assert "Kitchen Light" in card
    assert "device is offline" in card
    assert "Failed" in card


def test_routine_result_card_error():
    result = {
        "status": "error",
        "routine": "unknown routine",
        "reason": "unknown routine (known: good night, good morning, movie time)",
    }

    card = format_routine_result_card(result)

    assert "❌" in card
    assert "unknown routine" in card


def test_routine_result_card_with_compensations_and_security_alerts():
    result = {
        "status": "partial_failure",
        "routine": "good night",
        "summary": "5 succeeded, 2 failed (Kitchen Light, Front Door Lock)",
        "results": [
            {"status": "failed", "device": "Kitchen Light", "reason": "device is offline"},
            {"status": "failed", "device": "Front Door Lock", "reason": "device is offline"},
        ],
        "compensations": [
            {
                "failed_device": "Kitchen Light",
                "substitute_device": "Living Room Light",
                "compensating_action": "off",
                "status": "success",
            }
        ],
        "security_alerts": [
            {
                "severity": "CRITICAL",
                "device": "Front Door Lock",
                "channel": "sns",
                "message_id": "sns-alert-9999",
            }
        ],
    }

    card = format_routine_result_card(result)

    assert "🔄 Self-Healing Compensations" in card
    assert "Living Room Light" in card
    assert "🚨 Critical Security Escalations (AWS SNS)" in card
    assert "Front Door Lock" in card
    assert "sns-alert-9999" in card


def test_replenishment_card_renders_proposal():
    proposal = {
        "status": "proposed",
        "device": "Front Door Lock",
        "diagnosis": "Suspected dead CR123A battery",
        "replenishment": {
            "item_name": "Energizer CR123A Lithium 3V Batteries (2-Pack)",
            "asin": "B000IX214E",
            "price": "$9.98",
            "estimated_delivery": "Tomorrow by 8 PM with Prime",
        },
        "action": "add_to_amazon_cart",
    }
    card = format_replenishment_card(proposal)
    assert "🛒 Amazon Replenishment Proposal: Front Door Lock" in card
    assert "Energizer CR123A" in card
    assert "B000IX214E" in card
    assert "$9.98" in card
    assert "Confirmation Required" in card


def test_replenishment_card_renders_error():
    proposal = {
        "status": "error",
        "device": "Unknown Device",
        "reason": "device not found",
    }
    card = format_replenishment_card(proposal)
    assert "❌ Replenishment Proposal Failed" in card
    assert "device not found" in card


def test_security_alert_card_renders_critical_alert():
    alert = {
        "severity": "CRITICAL",
        "device": "Front Door Lock",
        "channel": "sns",
        "status": "escalated",
        "message_id": "sns-12345",
        "alert": {
            "reason": "state verification failed",
            "routine": "good night",
        },
    }
    card = format_security_alert_card(alert)
    assert "🚨 [CRITICAL] Security Alert: Front Door Lock" in card
    assert "SNS" in card
    assert "sns-12345" in card
    assert "state verification failed" in card
    assert "good night" in card


def test_security_alert_card_handles_missing_channel_and_non_critical_severity():
    alert = {
        "severity": "WARNING",
        "device": "Thermostat",
        "channel": None,
        "status": "warning",
        "message_id": None,
        "reason": "battery low",
    }
    card = format_security_alert_card(alert)
    assert "⚠️ [WARNING] Security Alert: Thermostat" in card
    assert "via SNS" in card
    assert "battery low" in card


def test_routine_result_card_renders_failed_compensation_truthfully():
    result = {
        "status": "partial_failure",
        "routine": "good night",
        "summary": "5 succeeded, 2 failed (Living Room Light, Office Desk Lamp)",
        "results": [
            {"status": "failed", "device": "Living Room Light", "reason": "device is offline"},
            {"status": "failed", "device": "Office Desk Lamp", "reason": "device is offline"},
        ],
        "compensations": [
            {
                "failed_device": "Living Room Light",
                "substitute_device": "Office Desk Lamp",
                "compensating_action": "off",
                "status": "failed",
            }
        ],
    }
    card = format_routine_result_card(result)
    assert "🔄 Self-Healing Compensations" in card
    assert "Office Desk Lamp" in card
    assert "attempted compensation for Living Room Light, but failed" in card


def test_adapter_status_card_renders():
    status = {
        "status": "ok",
        "active_adapter": "matter_bridge",
        "active_protocol": "matter-1.3",
        "available_adapters": {
            "matter_bridge": {
                "adapter": "MatterBridgeAdapter",
                "protocol": "matter-1.3",
                "ready": True,
                "status": "operational",
                "supported_clusters": [{"name": "OnOff"}],
            }
        },
    }
    card = format_adapter_status_card(status)
    assert "Smart-Home Device Adapters" in card
    assert "matter_bridge" in card
    assert "MatterBridgeAdapter" in card


def test_telemetry_card_renders():
    metrics = {
        "status": "ok",
        "total_actions": 50,
        "verified_successes": 48,
        "verification_failures": 2,
        "silent_failures_prevented": 2,
        "verification_pass_rate_pct": 96.0,
        "industry_unverified_failure_rate_pct": 18.4,
        "mean_actions_between_failures": 25.0,
        "compensations_executed": 3,
        "security_escalations_dispatched": 1,
        "benchmark_summary": "Prevented 2 silent routine failures.",
    }
    card = format_telemetry_card(metrics)
    assert "Veristead Reliability & Impact Telemetry" in card
    assert "- **Total Actions Executed:** 50" in card
    assert "18.4%" in card
    assert "25.0 actions" in card


def test_telemetry_card_renders_with_real_world_metrics():
    metrics = {
        "status": "ok",
        "total_actions": 100,
        "total_verified_executions": 100,
        "verified_successes": 95,
        "verification_failures": 5,
        "verification_pass_rate_pct": 95.0,
        "verification_success_rate_pct": 95.0,
        "silent_failures_prevented": 5,
        "routine_partial_failure_rate_pct": 14.3,
        "autonomous_self_healing_recovery_rate_pct": 80.0,
        "security_escalation_count": 2,
        "security_escalations_dispatched": 2,
        "industry_unverified_failure_rate_pct": 18.4,
        "mean_actions_between_failures": 20.0,
        "compensations_executed": 4,
        "benchmark_summary": "Prevented 5 silent routine failures.",
    }
    card = format_telemetry_card(metrics)
    assert "- **Total Verified Executions:** 100" in card
    assert "- **Verification Success Rate:** 95.0%" in card
    assert "- **Routine Partial Failure Rate:** 14.3%" in card
    assert "(vs 18–24% industry silent failure baseline)" in card
    assert "- **Autonomous Self-Healing Recovery Rate:** 80.0%" in card
    assert "- **Security Escalation Count:** 2" in card


def test_rich_card_multi_modal_schema_and_compatibility():
    """RichCard satisfies dict schema, interactive_actions, voice_speech, and string containment."""
    markdown_text = "# Test Card\nThis is a test presentation card."
    actions = [
        {"label": "Confirm Action", "tool": "confirm_and_execute_proposal", "parameters": {"proposal_id": "p1"}},
        {"label": "Dismiss", "tool": "forget_topic", "parameters": {"topic": "test"}},
    ]
    speech = "Alexa confirmed the test action."

    card = RichCard(markdown=markdown_text, interactive_actions=actions, voice_speech=speech)

    # 1. Multi-modal properties
    assert card.markdown == markdown_text
    assert card.interactive_actions == actions
    assert card.voice_speech == speech

    # 2. Dictionary interface
    assert isinstance(card, dict)
    assert card["markdown"] == markdown_text
    assert card["interactive_actions"] == actions
    assert card["voice_speech"] == speech
    d = card.to_dict()
    assert d["markdown"] == markdown_text

    # 3. String compatibility
    assert "Test Card" in card
    assert "presentation card" in card
    assert card.startswith("# Test")
    assert str(card) == markdown_text


def test_format_proposal_card():
    """format_proposal_card formats in-server proposals with interactive action chips."""
    proposal = {
        "proposal_id": "prop_test123",
        "device": "Thermostat",
        "action": "set:22",
        "command": "I'm cold",
        "message": "Increase thermostat to 22C?",
    }
    card = format_proposal_card(proposal)

    assert isinstance(card, RichCard)
    assert "Proposed Action: Thermostat" in card
    assert "set:22" in card
    assert "prop_test123" in card["markdown"]
    assert card.voice_speech == "Increase thermostat to 22C?"

    # Verify clickable chips
    assert len(card.interactive_actions) == 2
    assert card.interactive_actions[0]["label"] == "Confirm & Execute"
    assert card.interactive_actions[0]["tool"] == "confirm_and_execute_proposal"
    assert card.interactive_actions[0]["parameters"]["proposal_id"] == "prop_test123"


def test_format_proposal_execution_card():
    """format_proposal_execution_card renders verified post-execution physical state."""
    proposal = {
        "proposal_id": "prop_test123",
        "device": "Front Door Lock",
        "action": "lock",
    }
    execution = {
        "status": "success",
        "new_state": {"locked": True},
    }
    card = format_proposal_execution_card(proposal, execution)

    assert isinstance(card, RichCard)
    assert "Action Confirmed & Verified" in card
    assert "Front Door Lock" in card
    assert "locked" in card
    assert "prop_test123" in card["markdown"]
    assert len(card.interactive_actions) >= 1
    assert "Confirmed and verified" in card.voice_speech


def test_all_card_formatters_return_rich_cards_with_action_chips():
    """Every card formatter returns a RichCard with structured actions and voice speech."""
    devices = [
        {"name": "Kitchen Light", "room": "kitchen", "type": "light", "state": {"power": "off"}, "online": False}
    ]
    dev_card = format_device_status_card(devices)
    assert isinstance(dev_card, RichCard)
    assert len(dev_card.interactive_actions) > 0
    assert len(dev_card.voice_speech) > 0

    routine_res = {
        "status": "partial_failure",
        "routine": "good night",
        "summary": "5 succeeded, 1 failed (Kitchen Light)",
        "results": [{"status": "failed", "device": "Kitchen Light", "reason": "device is offline"}],
    }
    rout_card = format_routine_result_card(routine_res)
    assert isinstance(rout_card, RichCard)
    assert any("Retry" in a["label"] for a in rout_card.interactive_actions)
    assert len(rout_card.voice_speech) > 0

    prop = {
        "status": "proposed",
        "device": "Kitchen Light",
        "diagnosis": "Burned out bulb",
        "replenishment": {"item_name": "Hue Bulb", "price": "$14.99", "asin": "B12345"},
    }
    repl_card = format_replenishment_card(prop)
    assert isinstance(repl_card, RichCard)
    assert any("Add to Cart" in a["label"] for a in repl_card.interactive_actions)

    alert = {"device": "Front Door Lock", "severity": "CRITICAL", "channel": "sns", "status": "dispatched"}
    sec_card = format_security_alert_card(alert)
    assert isinstance(sec_card, RichCard)
    assert len(sec_card.interactive_actions) > 0


