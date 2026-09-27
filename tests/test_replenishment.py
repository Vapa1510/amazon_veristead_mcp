from veristead.tools import devices, memory
from veristead.tools.replenishment import propose_device_replenishment_impl


def _setup_db(tmp_path, monkeypatch):
    monkeypatch.setattr(devices, "DB_PATH", tmp_path / "devices.db")
    monkeypatch.setattr(memory, "DB_PATH", tmp_path / "memory.db")


def test_replenishment_offline_lock_diagnoses_battery(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    devices.simulate_offline_device_impl("Front Door Lock", offline=True)

    result = propose_device_replenishment_impl("Front Door Lock")

    assert result["status"] == "proposed"
    assert result["device"] == "Front Door Lock"
    assert result["device_type"] == "lock"
    assert result["online"] is False
    assert "battery" in result["diagnosis"].lower()
    assert result["replenishment"]["asin"] == "B000IX214E"
    assert result["replenishment"]["price"] == "$9.98"
    assert result["requires_confirmation"] is True
    assert result["auto_ordered"] is False
    assert "add_to_amazon_cart" in result["action"]


def test_replenishment_offline_light_diagnoses_bulb(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    devices.simulate_offline_device_impl("Kitchen Light", offline=True)

    result = propose_device_replenishment_impl("Kitchen Light")

    assert result["status"] == "proposed"
    assert result["device"] == "Kitchen Light"
    assert result["device_type"] == "light"
    assert result["online"] is False
    assert "bulb" in result["diagnosis"].lower()
    assert result["replenishment"]["asin"] == "B084138MG9"
    assert result["replenishment"]["price"] == "$15.99"


def test_replenishment_thermostat_diagnoses_battery(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    devices.simulate_offline_device_impl("Thermostat", offline=True)

    result = propose_device_replenishment_impl("Thermostat")

    assert result["status"] == "proposed"
    assert result["device"] == "Thermostat"
    assert result["device_type"] == "thermostat"
    assert result["replenishment"]["asin"] == "B00000J47L"
    assert result["replenishment"]["price"] == "$8.49"


def test_replenishment_garage_diagnoses_coin_cell(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    devices.simulate_offline_device_impl("Garage Door Opener", offline=True)

    result = propose_device_replenishment_impl("Garage Door Opener")

    assert result["status"] == "proposed"
    assert result["device"] == "Garage Door Opener"
    assert result["device_type"] == "garage"
    assert result["replenishment"]["asin"] == "B0002DSVS8"
    assert result["replenishment"]["price"] == "$6.25"


def test_replenishment_plug_diagnoses_hardware(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    devices.simulate_offline_device_impl("Bedroom Smart Plug", offline=True)

    result = propose_device_replenishment_impl("Bedroom Smart Plug")

    assert result["status"] == "proposed"
    assert result["device"] == "Bedroom Smart Plug"
    assert result["replenishment"]["asin"] == "B07KVD8QXX"


def test_replenishment_online_device_provides_preventive_proposal(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)

    result = propose_device_replenishment_impl("Living Room Light")

    assert result["status"] == "proposed"
    assert result["online"] is True
    assert "preventive" in result["diagnosis"].lower()
    assert result["requires_confirmation"] is True
    assert result["auto_ordered"] is False


def test_replenishment_unknown_device_returns_error(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)

    result = propose_device_replenishment_impl("Nonexistent Sauna")

    assert result["status"] == "error"
    assert "not found" in result["reason"].lower()


def test_replenishment_ambiguous_device_returns_error(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)

    result = propose_device_replenishment_impl("light")

    assert result["status"] == "error"
    assert "ambiguous" in result["reason"].lower()


def test_replenishment_persists_to_memory(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)

    propose_device_replenishment_impl("Front Door Lock")

    entries = memory.recall_context_impl("replenishment:front door lock")
    assert len(entries) > 0
    assert "Energizer" in entries[0]["detail"]


def test_replenishment_never_auto_orders_requires_confirmation(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)

    result = propose_device_replenishment_impl("Front Door Lock")

    assert result["auto_ordered"] is False
    assert result["requires_confirmation"] is True
    assert "Would you like me to add" in result["message"]


def test_replenishment_null_or_empty_device(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)

    res_none = propose_device_replenishment_impl(None)
    assert res_none["status"] == "error"
    assert "device not found" in res_none["reason"]

    res_empty = propose_device_replenishment_impl("")
    assert res_empty["status"] == "error"
    assert "device not found" in res_empty["reason"]
