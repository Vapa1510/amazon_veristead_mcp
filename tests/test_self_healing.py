from veristead.tools import cards, devices, memory


def _setup_db(tmp_path, monkeypatch):
    monkeypatch.setattr(devices, "DB_PATH", tmp_path / "devices.db")
    monkeypatch.setattr(memory, "DB_PATH", tmp_path / "memory.db")


def test_good_night_compensates_offline_kitchen_light(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    devices.simulate_offline_device_impl("Kitchen Light", offline=True)

    result = devices.run_routine_impl("good night")

    assert result["status"] == "partial_failure"
    assert "1 failed" in result["summary"]
    assert "Kitchen Light" in result["summary"]
    assert "Self-healing" in result["summary"]
    assert len(result["compensations"]) >= 1

    comp = next(c for c in result["compensations"] if c["failed_device"] == "Kitchen Light")
    assert comp["substitute_device"] == "Living Room Light"
    assert comp["compensating_action"] == "off"
    assert comp["status"] == "success"
    assert comp["verified_state"] == {"power": "off"}


def test_good_night_compensates_offline_bedroom_light_with_bedroom_plug(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    devices.simulate_offline_device_impl("Bedroom Light", offline=True)

    result = devices.run_routine_impl("good night")

    assert result["status"] == "partial_failure"
    comp = next(c for c in result["compensations"] if c["failed_device"] == "Bedroom Light")
    assert comp["substitute_device"] == "Bedroom Smart Plug"
    assert comp["compensating_action"] == "off"
    assert comp["status"] == "success"
    assert comp["verified_state"] == {"power": "off"}


def test_self_healing_writes_to_memory(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    devices.simulate_offline_device_impl("Kitchen Light", offline=True)

    devices.run_routine_impl("good night")

    entries = memory.recall_context_impl("self_healing:compensation")
    assert len(entries) > 0
    assert "Kitchen Light" in entries[0]["detail"]
    assert "Living Room Light" in entries[0]["detail"]


def test_self_healing_verifies_compensating_device_state(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    devices.simulate_offline_device_impl("Bedroom Light", offline=True)

    # Pre-condition: turn Bedroom Smart Plug on
    devices.execute_device_action_impl("Bedroom Smart Plug", "on")
    plug_before = devices.get_device_status_impl("Bedroom Smart Plug")[0]
    assert plug_before["state"]["power"] == "on"

    # Routine triggers compensation that turns plug off
    devices.run_routine_impl("good night")

    plug_after = devices.get_device_status_impl("Bedroom Smart Plug")[0]
    assert plug_after["state"]["power"] == "off"


def test_routine_card_renders_self_healing_section():
    result = {
        "status": "partial_failure",
        "routine": "good night",
        "summary": "6 succeeded, 1 failed (Kitchen Light) [Self-healing: compensated via Living Room Light (off)]",
        "results": [
            {"status": "success", "device": "Living Room Light", "new_state": {"power": "off"}},
            {"status": "failed", "device": "Kitchen Light", "reason": "device is offline"},
        ],
        "compensations": [
            {
                "failed_device": "Kitchen Light",
                "attempted_action": "off",
                "substitute_device": "Living Room Light",
                "compensating_action": "off",
                "status": "success",
                "reason": "ensure adjacent living room light is off",
            }
        ],
    }

    card = cards.format_routine_result_card(result)

    assert "🔄 Self-Healing Compensations" in card
    assert "Living Room Light" in card
    assert "compensated Kitchen Light" in card
    assert "🛡️" in card


def test_no_compensation_when_routine_succeeds_completely(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)

    result = devices.run_routine_impl("movie time")

    assert result["status"] == "ok"
    assert len(result["compensations"]) == 0
    card = cards.format_routine_result_card(result)
    assert "Self-Healing Compensations" not in card


def test_thermostat_failure_does_not_turn_lights_on(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    # Start with Living Room Light OFF
    devices.execute_device_action_impl("Living Room Light", "off")
    # Take Thermostat offline
    devices.simulate_offline_device_impl("Thermostat", offline=True)

    result = devices.run_routine_impl("good night")

    # The Thermostat failure should NOT trigger turning Living Room Light ON
    lr_light = devices.get_device_status_impl("Living Room Light")[0]
    assert lr_light["state"]["power"] == "off"
    for c in result.get("compensations", []):
        if c["failed_device"] == "Thermostat":
            assert c["compensating_action"] != "on"


def test_self_healing_when_substitute_is_offline(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    # Take Kitchen Light offline AND its substitute Living Room Light offline
    devices.simulate_offline_device_impl("Kitchen Light", offline=True)
    devices.simulate_offline_device_impl("Living Room Light", offline=True)

    result = devices.run_routine_impl("good night")

    assert result["status"] == "partial_failure"
    comp = next((c for c in result["compensations"] if c["failed_device"] == "Kitchen Light"), None)
    if comp:
        assert comp["status"] != "success"
    assert "compensated via Living Room Light" not in result["summary"]


def test_self_healing_ignores_null_or_invalid_inputs(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    assert devices._attempt_compensating_action(None, "off", "good night") is None
    assert devices._attempt_compensating_action("Kitchen Light", None, "good night") is None
