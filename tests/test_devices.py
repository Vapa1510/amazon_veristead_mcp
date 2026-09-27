from veristead.tools import devices


def test_get_all_devices_seeds_household(tmp_path, monkeypatch):
    monkeypatch.setattr(devices, "DB_PATH", tmp_path / "devices.db")

    result = devices.get_device_status_impl()

    names = {d["name"] for d in result}
    assert "Living Room Light" in names
    assert "Thermostat" in names
    assert "Garage Door Opener" in names
    assert "Office Desk Lamp" in names
    assert "Back Door Lock" in names
    assert len(result) == 10


def test_execute_action_verifies_new_state(tmp_path, monkeypatch):
    monkeypatch.setattr(devices, "DB_PATH", tmp_path / "devices.db")

    result = devices.execute_device_action_impl("Kitchen Light", "on")

    assert result["status"] == "success"
    assert result["new_state"]["power"] == "on"


def test_execute_action_on_offline_device_fails_honestly(tmp_path, monkeypatch):
    monkeypatch.setattr(devices, "DB_PATH", tmp_path / "devices.db")

    devices.simulate_offline_device_impl("Kitchen Light", offline=True)
    result = devices.execute_device_action_impl("Kitchen Light", "on")

    assert result["status"] == "failed"
    assert result["reason"] == "device is offline"


def test_execute_action_unknown_device(tmp_path, monkeypatch):
    monkeypatch.setattr(devices, "DB_PATH", tmp_path / "devices.db")

    result = devices.execute_device_action_impl("Garage Light", "on")

    assert result["status"] == "error"
    assert result["reason"] == "device not found"


def test_thermostat_set_action(tmp_path, monkeypatch):
    monkeypatch.setattr(devices, "DB_PATH", tmp_path / "devices.db")

    result = devices.execute_device_action_impl("Thermostat", "set:23")

    assert result["status"] == "success"
    assert result["new_state"]["temperature"] == 23


def test_run_routine_reports_partial_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(devices, "DB_PATH", tmp_path / "devices.db")

    # Take the kitchen light offline before running the routine that touches it.
    devices.simulate_offline_device_impl("Kitchen Light", offline=True)

    result = devices.run_routine_impl("good night")

    assert result["status"] == "partial_failure"
    assert "1 failed" in result["summary"]
    assert "Kitchen Light" in result["summary"]


def test_run_routine_unknown_name(tmp_path, monkeypatch):
    monkeypatch.setattr(devices, "DB_PATH", tmp_path / "devices.db")

    result = devices.run_routine_impl("spring cleaning")

    assert result["status"] == "error"


def test_execute_action_automatically_writes_to_memory(tmp_path, monkeypatch):
    from veristead.tools import memory
    monkeypatch.setattr(devices, "DB_PATH", tmp_path / "devices.db")
    monkeypatch.setattr(memory, "DB_PATH", tmp_path / "memory.db")

    devices.execute_device_action_impl("Kitchen Light", "on")

    memories = memory.view_memory_impl()
    assert len(memories) > 0
    assert "Kitchen Light" in memories[0]["detail"]


def test_bidirectional_device_name_lookup(tmp_path, monkeypatch):
    monkeypatch.setattr(devices, "DB_PATH", tmp_path / "devices.db")

    result = devices.execute_device_action_impl("the kitchen light", "on")

    assert result["status"] == "success"
    assert result["device"] == "Kitchen Light"


def test_ambiguous_device_name_lookup(tmp_path, monkeypatch):
    monkeypatch.setattr(devices, "DB_PATH", tmp_path / "devices.db")

    result = devices.execute_device_action_impl("light", "on")

    assert result["status"] == "error"
    assert "ambiguous device name" in result["reason"]
    assert "Living Room Light" in result["reason"]
    assert "Kitchen Light" in result["reason"]


def test_movie_time_routine(tmp_path, monkeypatch):
    monkeypatch.setattr(devices, "DB_PATH", tmp_path / "devices.db")

    result = devices.run_routine_impl("movie time")

    assert result["status"] == "ok"
    assert result["routine"] == "movie time"
    assert len(result["results"]) == 3


def test_good_night_expanded_covers_all_devices(tmp_path, monkeypatch):
    """Good night now touches 7 devices including new office lamp and back door lock."""
    monkeypatch.setattr(devices, "DB_PATH", tmp_path / "devices.db")

    result = devices.run_routine_impl("good night")

    assert result["status"] == "ok"
    assert len(result["results"]) == 7

    device_names = [r["device"] for r in result["results"]]
    assert "Back Door Lock" in device_names
    assert "Office Desk Lamp" in device_names


def test_plug_device_on_off(tmp_path, monkeypatch):
    monkeypatch.setattr(devices, "DB_PATH", tmp_path / "devices.db")

    result = devices.execute_device_action_impl("Bedroom Smart Plug", "on")

    assert result["status"] == "success"
    assert result["new_state"]["power"] == "on"


def test_garage_door_open_close(tmp_path, monkeypatch):
    monkeypatch.setattr(devices, "DB_PATH", tmp_path / "devices.db")

    opened = devices.execute_device_action_impl("Garage Door Opener", "open")
    assert opened["status"] == "success"
    assert opened["new_state"]["open"] is True

    closed = devices.execute_device_action_impl("Garage Door Opener", "close")
    assert closed["status"] == "success"
    assert closed["new_state"]["open"] is False


def test_thermostat_out_of_range_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(devices, "DB_PATH", tmp_path / "devices.db")

    result = devices.execute_device_action_impl("Thermostat", "set:99999")

    assert result["status"] == "error"
    assert "out of range" in result["reason"]


def test_verify_mismatch_reports_failed(tmp_path, monkeypatch):
    """If the re-read state does not match the expected write, report failed."""
    monkeypatch.setattr(devices, "DB_PATH", tmp_path / "devices.db")

    real_row_to_dict = devices._row_to_dict
    calls = {"n": 0}

    def flaky_row_to_dict(row):
        data = real_row_to_dict(row)
        calls["n"] += 1
        # First call is the pre-action read; second is the post-action verify.
        if calls["n"] >= 2 and data["name"] == "Kitchen Light":
            return {**data, "state": {"power": "off"}}
        return data

    monkeypatch.setattr(devices, "_row_to_dict", flaky_row_to_dict)

    result = devices.execute_device_action_impl("Kitchen Light", "on")

    assert result["status"] == "failed"
    assert result["reason"] == "state verification failed"
    assert result["expected_state"]["power"] == "on"
    assert result["actual_state"]["power"] == "off"


def test_get_room_devices_returns_multiple(tmp_path, monkeypatch):
    """Bedroom now has 2 devices (light + smart plug), garage has 2 (opener + lock)."""
    monkeypatch.setattr(devices, "DB_PATH", tmp_path / "devices.db")

    bedroom = devices.get_room_devices_impl("bedroom")
    assert len(bedroom) == 2

    garage = devices.get_room_devices_impl("garage")
    assert len(garage) == 2

    opener = next(d for d in garage if d["name"] == "Garage Door Opener")
    assert opener["type"] == "garage"


def test_routine_includes_compensations_and_security_alerts_keys(tmp_path, monkeypatch):
    """Every routine response structure includes compensations and security_alerts lists."""
    monkeypatch.setattr(devices, "DB_PATH", tmp_path / "devices.db")

    result = devices.run_routine_impl("movie time")

    assert "compensations" in result
    assert "security_alerts" in result
    assert isinstance(result["compensations"], list)
    assert isinstance(result["security_alerts"], list)


def test_execute_device_action_invalid_inputs(tmp_path, monkeypatch):
    monkeypatch.setattr(devices, "DB_PATH", tmp_path / "devices.db")
    res1 = devices.execute_device_action_impl(None, "on")
    assert res1["status"] == "error"
    res2 = devices.execute_device_action_impl("Kitchen Light", None)
    assert res2["status"] == "error"


def test_run_routine_invalid_name(tmp_path, monkeypatch):
    monkeypatch.setattr(devices, "DB_PATH", tmp_path / "devices.db")
    res = devices.run_routine_impl(None)
    assert res["status"] == "error"


def test_garage_door_rejects_on_off_with_guidance(tmp_path, monkeypatch):
    """Garage door strictly rejects on/off with clear guidance to use open/close."""
    monkeypatch.setattr(devices, "DB_PATH", tmp_path / "devices.db")

    res_on = devices.execute_device_action_impl("Garage Door Opener", "on")
    assert res_on["status"] == "error"
    assert "garage door opener does not support 'on'" in res_on["reason"]
    assert "use 'open' or 'close' instead" in res_on["reason"]

    res_off = devices.execute_device_action_impl("Garage Door Opener", "off")
    assert res_off["status"] == "error"
    assert "garage door opener does not support 'off'" in res_off["reason"]
    assert "use 'open' or 'close' instead" in res_off["reason"]


def test_thermostat_fahrenheit_and_celsius_bounds(tmp_path, monkeypatch):
    """Thermostat accepts Celsius and Fahrenheit in residential safe bounds, rejecting unsafe temps."""
    monkeypatch.setattr(devices, "DB_PATH", tmp_path / "devices.db")

    # Valid Celsius
    res_c = devices.execute_device_action_impl("Thermostat", "set:22C")
    assert res_c["status"] == "success"
    assert res_c["new_state"]["temperature"] == 22

    # Valid Fahrenheit (72F -> 22C)
    res_f = devices.execute_device_action_impl("Thermostat", "set:72F")
    assert res_f["status"] == "success"
    assert res_f["new_state"]["temperature"] == 22

    # Implicit Fahrenheit in 50..90 range (68 -> 20C)
    res_f_imp = devices.execute_device_action_impl("Thermostat", "set:68")
    assert res_f_imp["status"] == "success"
    assert res_f_imp["new_state"]["temperature"] == 20

    # Unsafe temperature low
    res_low = devices.execute_device_action_impl("Thermostat", "set:5")
    assert res_low["status"] == "error"
    assert "out of range" in res_low["reason"]

    # Unsafe temperature high
    res_high = devices.execute_device_action_impl("Thermostat", "set:105")
    assert res_high["status"] == "error"
    assert "out of range" in res_high["reason"]

    # Unsafe temperature between 32C and 50F (e.g. 40)
    res_mid = devices.execute_device_action_impl("Thermostat", "set:40")
    assert res_mid["status"] == "error"
    assert "out of range" in res_mid["reason"]

    # Valid float Celsius (21.0 -> 21C)
    res_float_c = devices.execute_device_action_impl("Thermostat", "set:21.0")
    assert res_float_c["status"] == "success"
    assert res_float_c["new_state"]["temperature"] == 21

    # Valid float Fahrenheit (71.6F -> 22C)
    res_float_f = devices.execute_device_action_impl("Thermostat", "set:71.6F")
    assert res_float_f["status"] == "success"
    assert res_float_f["new_state"]["temperature"] == 22


def test_simulate_hardware_drift_enables_and_disables(tmp_path, monkeypatch):
    """simulate_hardware_drift_impl toggles drift flag for matching device."""
    monkeypatch.setattr(devices, "DB_PATH", tmp_path / "devices.db")
    devices.reset_hardware_drift()

    res_on = devices.simulate_hardware_drift_impl("Kitchen Light", True)
    assert res_on["status"] == "ok"
    assert res_on["device"] == "Kitchen Light"
    assert res_on["drift"] is True

    res_off = devices.simulate_hardware_drift_impl("Kitchen Light", False)
    assert res_off["status"] == "ok"
    assert res_off["drift"] is False
    devices.reset_hardware_drift()


def test_hardware_drift_causes_state_verification_failure(tmp_path, monkeypatch):
    """When hardware drift occurs, silent write failure is caught by post-action verify."""
    monkeypatch.setattr(devices, "DB_PATH", tmp_path / "devices.db")
    devices.reset_hardware_drift()

    # Enable hardware drift: physical hardware drops write
    devices.simulate_hardware_drift_impl("Kitchen Light", True)

    result = devices.execute_device_action_impl("Kitchen Light", "on")
    assert result["status"] == "failed"
    assert result["reason"] == "state verification failed"
    assert result["expected_state"] == {"power": "on"}
    assert result["actual_state"] == {"power": "off"}

    # Turn off drift and verify write succeeds and is verified
    devices.simulate_hardware_drift_impl("Kitchen Light", False)
    result2 = devices.execute_device_action_impl("Kitchen Light", "on")
    assert result2["status"] == "success"
    assert result2["new_state"] == {"power": "on"}
    devices.reset_hardware_drift()


def test_simulate_hardware_drift_invalid_device(tmp_path, monkeypatch):
    monkeypatch.setattr(devices, "DB_PATH", tmp_path / "devices.db")
    res1 = devices.simulate_hardware_drift_impl(None, True)
    assert res1["status"] == "error"
    res2 = devices.simulate_hardware_drift_impl("Ghost Light", True)
    assert res2["status"] == "error"
    assert "not found" in res2["reason"]



