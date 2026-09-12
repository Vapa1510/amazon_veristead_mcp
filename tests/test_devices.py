from veristead.tools import devices


def test_get_all_devices_seeds_household(tmp_path, monkeypatch):
    monkeypatch.setattr(devices, "DB_PATH", tmp_path / "devices.db")

    result = devices.get_device_status_impl()

    names = {d["name"] for d in result}
    assert "Living Room Light" in names
    assert "Thermostat" in names
    assert len(result) == 5


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
