from veristead.tools import devices, memory


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


def test_get_device_status_filters_by_room(tmp_path, monkeypatch):
    monkeypatch.setattr(devices, "DB_PATH", tmp_path / "devices.db")

    result = devices.get_device_status_impl("living room")

    names = {d["name"] for d in result}
    assert names == {"Living Room Light", "Thermostat"}


def test_get_room_devices_exact_room_match(tmp_path, monkeypatch):
    monkeypatch.setattr(devices, "DB_PATH", tmp_path / "devices.db")

    result = devices.get_room_devices_impl("kitchen")

    assert len(result) == 1
    assert result[0]["name"] == "Kitchen Light"


def test_simulate_offline_then_online_restores_device(tmp_path, monkeypatch):
    monkeypatch.setattr(devices, "DB_PATH", tmp_path / "devices.db")

    devices.simulate_offline_device_impl("Kitchen Light", offline=True)
    devices.simulate_offline_device_impl("Kitchen Light", offline=False)
    result = devices.execute_device_action_impl("Kitchen Light", "on")

    assert result["status"] == "success"


def test_thermostat_invalid_temperature_returns_error(tmp_path, monkeypatch):
    monkeypatch.setattr(devices, "DB_PATH", tmp_path / "devices.db")

    result = devices.execute_device_action_impl("Thermostat", "set:not-a-number")

    assert result["status"] == "error"


def test_fuzzy_device_name_resolves_to_single_match(tmp_path, monkeypatch):
    """'the kitchen light' should resolve the same way get_device_status does,
    not fail with 'device not found' just because it isn't an exact match."""
    monkeypatch.setattr(devices, "DB_PATH", tmp_path / "devices.db")

    result = devices.execute_device_action_impl("the kitchen light", "on")

    assert result["status"] == "success"
    assert result["device"] == "Kitchen Light"


def test_ambiguous_device_query_lists_candidates(tmp_path, monkeypatch):
    """A query matching more than one device should ask for disambiguation
    instead of silently picking one."""
    monkeypatch.setattr(devices, "DB_PATH", tmp_path / "devices.db")

    result = devices.execute_device_action_impl("light", "on")

    assert result["status"] == "ambiguous"
    assert len(result["candidates"]) == 3


def test_execute_device_action_writes_to_memory(tmp_path, monkeypatch):
    """Regression test: a single action (not just a routine) must leave a
    memory trace, per the Pillar 5 promise."""
    devices_db = tmp_path / "devices.db"
    memory_db = tmp_path / "memory.db"
    monkeypatch.setattr(devices, "DB_PATH", devices_db)
    monkeypatch.setattr(memory, "DB_PATH", memory_db)

    devices.execute_device_action_impl("Kitchen Light", "on")
    entries = memory.view_memory_impl()

    assert len(entries) == 1
    assert entries[0]["topic"] == "kitchen"
    assert "Kitchen Light" in entries[0]["detail"]


def test_execute_device_action_offline_also_writes_memory(tmp_path, monkeypatch):
    devices_db = tmp_path / "devices.db"
    memory_db = tmp_path / "memory.db"
    monkeypatch.setattr(devices, "DB_PATH", devices_db)
    monkeypatch.setattr(memory, "DB_PATH", memory_db)

    devices.simulate_offline_device_impl("Kitchen Light", offline=True)
    devices.execute_device_action_impl("Kitchen Light", "on")
    entries = memory.view_memory_impl()

    assert len(entries) == 1
    assert "offline" in entries[0]["detail"]
