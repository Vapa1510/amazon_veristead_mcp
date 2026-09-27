"""Tests for the In-Server Stateful Orchestrator (Propose -> Confirm -> Execute loop)."""
from __future__ import annotations

import json
from veristead.tools import devices, memory, telemetry
from veristead.tools.orchestrator import (
    cancel_proposal_impl,
    confirm_and_execute_proposal_impl,
    get_pending_proposals_impl,
    orchestrate_natural_language_command_impl,
)


class _FakeBedrockClient:
    def __init__(self, response_text=None, raise_exc=None):
        self._response_text = response_text
        self._raise_exc = raise_exc

    def converse(self, **kwargs):
        if self._raise_exc:
            raise self._raise_exc
        return {"output": {"message": {"content": [{"text": self._response_text}]}}}


def _setup_test_env(tmp_path, monkeypatch):
    """Seed test environment with temporary SQLite databases."""
    monkeypatch.setattr(devices, "DB_PATH", tmp_path / "devices.db")
    monkeypatch.setattr(memory, "DB_PATH", tmp_path / "memory.db")
    monkeypatch.setattr(telemetry, "DB_PATH", tmp_path / "telemetry.db")
    from veristead.tools.orchestrator import reset_proposals
    reset_proposals()


def test_orchestrate_propose_only_does_not_mutate(tmp_path, monkeypatch):
    """orchestrate with auto_confirm=False creates a pending proposal without mutating hardware."""
    _setup_test_env(tmp_path, monkeypatch)

    res = orchestrate_natural_language_command_impl("I'm cold", auto_confirm=False)

    assert res["status"] == "proposed"
    assert res["orchestrated"] is True
    assert res["auto_confirmed"] is False
    assert res["device"] == "Thermostat"
    assert res["action"] == "set:23"
    assert "proposal_id" in res
    assert res["proposal_id"].startswith("prop_")
    assert res["requires_confirmation"] is True

    # Card and interactive chips
    assert "card" in res
    assert "💡 Proposed Action" in res["card"]
    assert len(res["interactive_actions"]) >= 2
    labels = [a["label"] for a in res["interactive_actions"]]
    assert "Confirm & Execute" in labels
    assert "Cancel" in labels

    # Confirm device was not mutated yet
    status = devices.get_device_status_impl("Thermostat")
    assert status[0]["state"]["temperature"] == 21


def test_confirm_and_execute_proposal_verifies_state(tmp_path, monkeypatch):
    """confirm_and_execute_proposal executes the action through Request -> Execute -> Verify -> Confirm."""
    _setup_test_env(tmp_path, monkeypatch)

    # 1. Create proposal
    proposal = orchestrate_natural_language_command_impl("I'm cold", auto_confirm=False)
    proposal_id = proposal["proposal_id"]

    # 2. Confirm and execute
    exec_res = confirm_and_execute_proposal_impl(proposal_id)

    assert exec_res["status"] == "success"
    assert exec_res["orchestrated"] is True
    assert exec_res["proposal_id"] == proposal_id
    assert exec_res["device"] == "Thermostat"
    assert exec_res["action"] == "set:23"
    assert exec_res["verified_state"]["temperature"] == 23
    assert "Confirmed and verified" in exec_res["voice_speech"]

    # Verify post-execution hardware state in SQLite
    status_after = devices.get_device_status_impl("Thermostat")
    assert status_after[0]["state"]["temperature"] == 23

    # Attempting to re-execute the same proposal returns an error
    dup_res = confirm_and_execute_proposal_impl(proposal_id)
    assert dup_res["status"] == "error"
    assert "already been executed" in dup_res["reason"]


def test_orchestrate_auto_confirm_single_round_trip(tmp_path, monkeypatch):
    """orchestrate with auto_confirm=True executes the verified action in a single round-trip."""
    _setup_test_env(tmp_path, monkeypatch)

    res = orchestrate_natural_language_command_impl("I'm cold", auto_confirm=True)

    assert res["status"] == "success"
    assert res["orchestrated"] is True
    assert res["auto_confirmed"] is True
    assert res["device"] == "Thermostat"
    assert res["action"] == "set:23"
    assert res["verified_state"]["temperature"] == 23

    # Verified hardware state
    status = devices.get_device_status_impl("Thermostat")
    assert status[0]["state"]["temperature"] == 23


def test_orchestrate_with_bedrock_client(tmp_path, monkeypatch):
    """Orchestrator correctly uses Bedrock Converse API when model is configured."""
    _setup_test_env(tmp_path, monkeypatch)
    monkeypatch.setenv("BEDROCK_MODEL_ID", "test-model-id")

    fake_resp = json.dumps({
        "device": "Office Desk Lamp",
        "action": "on",
        "message": "Turn on the office desk lamp for working?",
    })
    client = _FakeBedrockClient(response_text=fake_resp)

    res = orchestrate_natural_language_command_impl("turn on office light", auto_confirm=True, client=client)

    assert res["status"] == "success"
    assert res["device"] == "Office Desk Lamp"
    assert res["action"] == "on"
    assert res["verified_state"]["power"] == "on"


def test_orchestrator_handles_offline_device_honestly(tmp_path, monkeypatch):
    """When a device is offline, confirmation reports honest verification failure."""
    _setup_test_env(tmp_path, monkeypatch)

    # Take Kitchen Light offline
    devices.simulate_offline_device_impl("Kitchen Light", offline=True)

    # Orchestrate turning it on
    proposal = orchestrate_natural_language_command_impl("turn on the kitchen light", auto_confirm=False)
    prop_id = proposal["proposal_id"]

    # Confirm proposal
    exec_res = confirm_and_execute_proposal_impl(prop_id)

    assert exec_res["status"] == "failed"
    assert exec_res["reason"] == "device is offline"
    assert "failed verification" in exec_res["voice_speech"]


def test_orchestrator_cancel_proposal(tmp_path, monkeypatch):
    """cancel_proposal cancels a pending proposal."""
    _setup_test_env(tmp_path, monkeypatch)

    prop = orchestrate_natural_language_command_impl("I'm cold", auto_confirm=False)
    prop_id = prop["proposal_id"]

    cancel_res = cancel_proposal_impl(prop_id)
    assert cancel_res["status"] == "cancelled"

    # Attempting to cancel non-existent proposal returns error
    bad_cancel = cancel_proposal_impl("prop_does_not_exist")
    assert bad_cancel["status"] == "error"


def test_orchestrator_invalid_inputs(tmp_path, monkeypatch):
    """Orchestrator rejects empty commands or invalid proposal IDs."""
    _setup_test_env(tmp_path, monkeypatch)

    res1 = orchestrate_natural_language_command_impl("")
    assert res1["status"] == "error"
    assert "empty command" in res1["reason"]

    res2 = confirm_and_execute_proposal_impl("")
    assert res2["status"] == "error"

    res3 = confirm_and_execute_proposal_impl("nonexistent_id")
    assert res3["status"] == "error"
    assert "not found" in res3["reason"]


def test_get_pending_proposals_listing(tmp_path, monkeypatch):
    """get_pending_proposals_impl returns all active pending proposals."""
    _setup_test_env(tmp_path, monkeypatch)

    prop1 = orchestrate_natural_language_command_impl("I'm cold", auto_confirm=False)
    pending = get_pending_proposals_impl()
    assert any(p["proposal_id"] == prop1["proposal_id"] for p in pending)


def test_server_registers_all_16_tools():
    """Server exposes all 16 tools including the two stateful orchestrator tools."""
    from veristead.server import (
        confirm_and_execute_proposal,
        escalate_security_alert,
        execute_device_action,
        forget_topic,
        get_adapter_status,
        get_device_status,
        get_reliability_metrics,
        get_room_devices,
        get_verification_telemetry,
        handle_natural_language_command,
        orchestrate_natural_language_command,
        propose_device_replenishment,
        recall_context,
        run_routine,
        simulate_offline_device,
        view_memory,
    )
    tools = [
        propose_device_replenishment,
        escalate_security_alert,
        execute_device_action,
        get_device_status,
        get_room_devices,
        run_routine,
        simulate_offline_device,
        recall_context,
        view_memory,
        forget_topic,
        handle_natural_language_command,
        get_adapter_status,
        get_reliability_metrics,
        get_verification_telemetry,
        confirm_and_execute_proposal,
        orchestrate_natural_language_command,
    ]
    assert len(tools) == 16
    for t in tools:
        assert callable(t)
