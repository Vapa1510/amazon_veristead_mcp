"""Unit tests for Veristead Hardware Adapters (Pillars 1 & 7).

Tests the pluggable adapter architecture across MockSQLite, Home Assistant REST,
and Matter 1.3 standard cluster command bridge.
"""
from __future__ import annotations

import pytest
from veristead.adapters import (
    BaseDeviceAdapter,
    HomeAssistantAdapter,
    MatterBridgeAdapter,
    MockSQLiteAdapter,
    get_active_adapter,
    get_adapter_status_impl,
    reset_active_adapter,
    set_active_adapter,
)
from veristead.tools import cards, devices, memory


def _setup_db(tmp_path, monkeypatch):
    monkeypatch.setattr(devices, "DB_PATH", tmp_path / "devices.db")
    monkeypatch.setattr(memory, "DB_PATH", tmp_path / "memory.db")


# ── BaseDeviceAdapter Contract ───────────────────────────────────────────

def test_base_adapter_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        BaseDeviceAdapter()  # type: ignore


# ── MockSQLiteAdapter Tests ──────────────────────────────────────────────

def test_mock_sqlite_adapter_device_status_and_filtering(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    adapter = MockSQLiteAdapter()

    assert adapter.name == "mock_sqlite"
    assert adapter.protocol == "sqlite-virtual-home"

    devs = adapter.get_devices()
    assert len(devs) == 10

    kitchen = adapter.get_devices("Kitchen Light")
    assert len(kitchen) == 1
    assert kitchen[0]["name"] == "Kitchen Light"

    living_room = adapter.get_room_devices("living room")
    assert len(living_room) >= 2


def test_mock_sqlite_adapter_execute_action_verifies_state(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    adapter = MockSQLiteAdapter()

    result = adapter.execute_action("Kitchen Light", "on")
    assert result["status"] == "success"
    assert result["new_state"] == {"power": "on"}

    # Re-verify through adapter read
    status = adapter.get_devices("Kitchen Light")[0]
    assert status["state"]["power"] == "on"


def test_mock_sqlite_adapter_offline_device_fails_honestly(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    adapter = MockSQLiteAdapter()

    adapter.simulate_offline("Front Door Lock", offline=True)
    result = adapter.execute_action("Front Door Lock", "unlock")

    assert result["status"] == "failed"
    assert result["reason"] == "device is offline"


def test_mock_sqlite_adapter_status_metadata(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    adapter = MockSQLiteAdapter()
    status = adapter.get_status()

    assert status["adapter"] == "MockSQLiteAdapter"
    assert status["connected"] is True
    assert status["hermetic"] is True
    assert status["device_count"] == 10


# ── HomeAssistantAdapter Tests ───────────────────────────────────────────

class _MockHAHttpClient:
    """Mock HTTP client simulating Home Assistant REST API endpoints."""

    def __init__(self, entity_states: dict | None = None, service_fail: bool = False):
        self.entity_states = entity_states or {
            "light.kitchen_light": {
                "entity_id": "light.kitchen_light",
                "state": "off",
                "attributes": {"friendly_name": "Kitchen Light", "room": "kitchen"},
            },
            "lock.front_door_lock": {
                "entity_id": "lock.front_door_lock",
                "state": "locked",
                "attributes": {"friendly_name": "Front Door Lock", "room": "entryway"},
            },
            "climate.thermostat": {
                "entity_id": "climate.thermostat",
                "state": "heat",
                "attributes": {"friendly_name": "Thermostat", "temperature": 21, "room": "living room"},
            },
            "cover.garage_door_opener": {
                "entity_id": "cover.garage_door_opener",
                "state": "closed",
                "attributes": {"friendly_name": "Garage Door Opener", "room": "garage"},
            },
        }
        self.service_fail = service_fail
        self.last_service_call = None

    def request(self, method: str, url: str, json: dict | None = None, headers: dict | None = None):
        class _Resp:
            def __init__(self, code: int, data: any):
                self.status_code = code
                self._data = data

            def json(self):
                return self._data

        if method == "GET" and url.endswith("/api/states"):
            return _Resp(200, list(self.entity_states.values()))

        if method == "GET" and "/api/states/" in url:
            entity_id = url.split("/api/states/")[1]
            if entity_id in self.entity_states:
                return _Resp(200, self.entity_states[entity_id])
            return _Resp(404, {"message": "Entity not found"})

        if method == "POST" and "/api/services/" in url:
            if self.service_fail:
                return _Resp(500, {"message": "Internal Home Assistant Error"})
            self.last_service_call = (url, json)
            # Simulate mutation in state store
            if json and "entity_id" in json:
                eid = json["entity_id"]
                if eid in self.entity_states:
                    if self.entity_states[eid].get("state") not in ("unavailable", "unknown"):
                        if "turn_on" in url:
                            self.entity_states[eid]["state"] = "on"
                        elif "turn_off" in url:
                            self.entity_states[eid]["state"] = "off"
                        elif "unlock" in url:
                            self.entity_states[eid]["state"] = "unlocked"
                        elif "lock" in url:
                            self.entity_states[eid]["state"] = "locked"
                        elif "open_cover" in url:
                            self.entity_states[eid]["state"] = "open"
                        elif "close_cover" in url:
                            self.entity_states[eid]["state"] = "closed"
                        elif "set_temperature" in url:
                            self.entity_states[eid]["attributes"]["temperature"] = json.get("temperature", 21)
            return _Resp(200, [{"entity_id": json.get("entity_id")}])

        return _Resp(404, {})


def test_home_assistant_adapter_resolution_and_headers():
    ha = HomeAssistantAdapter(base_url="http://test-ha.local:8123", access_token="secret_token_123")
    assert ha.resolve_entity_id("Kitchen Light") == "light.kitchen_light"
    assert ha.resolve_entity_id("Front Door Lock") == "lock.front_door_lock"
    assert ha.resolve_entity_id("Thermostat") == "climate.thermostat"
    assert ha.resolve_entity_id("custom.my_fan") == "custom.my_fan"

    headers = ha._headers()
    assert headers["Authorization"] == "Bearer secret_token_123"
    assert headers["Content-Type"] == "application/json"


def test_home_assistant_adapter_get_devices_parses_states():
    mock_client = _MockHAHttpClient()
    ha = HomeAssistantAdapter(access_token="token", http_client=mock_client)

    devs = ha.get_devices()
    assert len(devs) == 4
    names = {d["name"] for d in devs}
    assert "Kitchen Light" in names
    assert "Front Door Lock" in names
    assert "Thermostat" in names


def test_home_assistant_adapter_execute_action_verifies_state():
    mock_client = _MockHAHttpClient()
    ha = HomeAssistantAdapter(access_token="token", http_client=mock_client)

    result = ha.execute_action("Kitchen Light", "on")
    assert result["status"] == "success"
    assert result["verified"] is True
    assert result["new_state"] == {"power": "on"}
    assert result["adapter"] == "home_assistant"

    # Lock action
    lock_res = ha.execute_action("Front Door Lock", "unlock")
    assert lock_res["status"] == "success"
    assert lock_res["new_state"] == {"locked": False}

    # Thermostat action
    therm_res = ha.execute_action("Thermostat", "set:24")
    assert therm_res["status"] == "success"
    assert therm_res["new_state"] == {"temperature": 24}


def test_home_assistant_adapter_service_failure_reported():
    mock_client = _MockHAHttpClient(service_fail=True)
    ha = HomeAssistantAdapter(access_token="token", http_client=mock_client)

    result = ha.execute_action("Kitchen Light", "on")
    assert result["status"] == "failed"
    assert "HTTP 500" in result["reason"]


def test_home_assistant_adapter_offline_device():
    mock_client = _MockHAHttpClient(entity_states={
        "light.kitchen_light": {
            "entity_id": "light.kitchen_light",
            "state": "unavailable",
            "attributes": {"friendly_name": "Kitchen Light"},
        }
    })
    ha = HomeAssistantAdapter(access_token="token", http_client=mock_client)

    result = ha.execute_action("Kitchen Light", "on")
    assert result["status"] == "failed"
    assert "offline" in result["reason"]


def test_home_assistant_adapter_state_mismatch_fails_honestly():
    class _MismatchClient:
        def request(self, method, url, json=None, headers=None):
            class _Resp:
                status_code = 200
                def json(self):
                    # Service says ok, but state read still returns 'off' when 'on' was requested!
                    return {
                        "entity_id": "light.kitchen_light",
                        "state": "off",
                        "attributes": {"friendly_name": "Kitchen Light"},
                    }
            return _Resp()

    ha = HomeAssistantAdapter(access_token="token", http_client=_MismatchClient())
    result = ha.execute_action("Kitchen Light", "on")

    assert result["status"] == "failed"
    assert result["reason"] == "state verification failed"
    assert result["expected_state"] == {"power": "on"}
    assert result["actual_state"] == {"power": "off"}


def test_home_assistant_adapter_status_and_standby():
    ha_no_token = HomeAssistantAdapter(access_token="")
    status = ha_no_token.get_status()
    assert status["connected"] is False
    assert status["status"] == "standby_ready"

    ha_with_token = HomeAssistantAdapter(access_token="tok123")
    status_tok = ha_with_token.get_status()
    assert status_tok["connected"] is True
    assert status_tok["status"] == "connected"
    assert "states" in status_tok["endpoints"]


# ── MatterBridgeAdapter Tests ────────────────────────────────────────────

def test_matter_bridge_supported_clusters():
    matter = MatterBridgeAdapter()
    status = matter.get_status()

    assert status["adapter"] == "MatterBridgeAdapter"
    assert status["protocol"] == "matter-1.3"
    assert status["fabric_id"] == "VERISTEAD-FABRIC-001"
    assert len(status["supported_clusters"]) == 5

    cluster_names = [c["name"] for c in status["supported_clusters"]]
    assert "OnOff" in cluster_names
    assert "DoorLock" in cluster_names
    assert "Thermostat" in cluster_names
    assert "WindowCovering" in cluster_names


def test_matter_bridge_invoke_and_verify_on_off():
    matter = MatterBridgeAdapter()

    res = matter.execute_action("Living Room Light", "on")
    assert res["status"] == "success"
    assert res["verified"] is True
    assert res["new_state"] == {"power": "on"}
    assert res["adapter"] == "matter_bridge"
    assert res["matter_cluster"] == "0x6"

    # Turn off
    res_off = matter.execute_action("Living Room Light", "off")
    assert res_off["status"] == "success"
    assert res_off["new_state"] == {"power": "off"}


def test_matter_bridge_invoke_and_verify_door_lock():
    matter = MatterBridgeAdapter()

    res = matter.execute_action("Front Door Lock", "unlock")
    assert res["status"] == "success"
    assert res["new_state"] == {"locked": False}

    res_lock = matter.execute_action("Front Door Lock", "lock")
    assert res_lock["status"] == "success"
    assert res_lock["new_state"] == {"locked": True}


def test_matter_bridge_invoke_and_verify_thermostat():
    matter = MatterBridgeAdapter()

    res = matter.execute_action("Thermostat", "set:23")
    assert res["status"] == "success"
    assert res["new_state"] == {"temperature": 23}


def test_matter_bridge_offline_node_fails():
    nodes = {
        "offline_light": {
            "name": "Offline Light",
            "node_id": "0x99",
            "endpoint_id": 1,
            "cluster_id": 0x0006,
            "type": "light",
            "room": "attic",
            "online": False,
            "attributes": {0x0000: False},
        }
    }
    matter = MatterBridgeAdapter(commissioned_nodes=nodes)
    res = matter.execute_action("Offline Light", "on")

    assert res["status"] == "failed"
    assert "offline" in res["reason"]


# ── Active Adapter Switching & Inspection Tests ──────────────────────────

def test_active_adapter_lifecycle():
    reset_active_adapter()
    assert get_active_adapter().name == "mock_sqlite"

    matter = MatterBridgeAdapter()
    set_active_adapter(matter)
    assert get_active_adapter().name == "matter_bridge"

    with pytest.raises(TypeError):
        set_active_adapter("invalid_string_adapter")  # type: ignore

    reset_active_adapter()
    assert get_active_adapter().name == "mock_sqlite"


def test_get_adapter_status_tool_implementation(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    reset_active_adapter()

    status = get_adapter_status_impl()
    assert status["status"] == "ok"
    assert status["active_adapter"] == "mock_sqlite"
    assert "mock_sqlite" in status["available_adapters"]
    assert "home_assistant" in status["available_adapters"]
    assert "matter_bridge" in status["available_adapters"]
    assert status["verification_enforced"] is True


def test_format_adapter_status_card():
    status = {
        "status": "ok",
        "active_adapter": "mock_sqlite",
        "active_protocol": "sqlite-virtual-home",
        "available_adapters": {
            "mock_sqlite": {
                "adapter": "MockSQLiteAdapter",
                "protocol": "sqlite-virtual-home",
                "ready": True,
                "status": "online",
                "description": "Hermetic SQLite mock",
            },
            "home_assistant": {
                "adapter": "HomeAssistantAdapter",
                "protocol": "rest+websocket",
                "ready": True,
                "status": "connected",
                "supported_domains": ["light", "switch", "lock"],
            },
            "matter_bridge": {
                "adapter": "MatterBridgeAdapter",
                "protocol": "matter-1.3",
                "ready": True,
                "status": "operational",
                "supported_clusters": [{"name": "OnOff"}, {"name": "DoorLock"}],
            },
        },
    }

    card = cards.format_adapter_status_card(status)
    assert "Smart-Home Device Adapters" in card
    assert "MockSQLiteAdapter" in card
    assert "HomeAssistantAdapter" in card
    assert "MatterBridgeAdapter" in card
    assert "Request → Execute → Verify → Confirm" in card


def test_mock_sqlite_adapter_with_custom_db_path(tmp_path):
    custom_db = tmp_path / "custom_test.db"
    adapter = MockSQLiteAdapter(db_path=custom_db)
    assert adapter.active_db_path == custom_db

    devs = adapter.get_devices()
    assert len(devs) == 10
    assert custom_db.exists()

    res = adapter.execute_action("Kitchen Light", "on")
    assert res["status"] == "success"


def test_home_assistant_adapter_temperature_range_and_invalid():
    ha = HomeAssistantAdapter(access_token="tok")
    # Out of range low
    res_low = ha.execute_action("Thermostat", "set:5")
    assert res_low["status"] == "error"
    assert "out of range" in res_low["reason"]

    # Out of range high
    res_high = ha.execute_action("Thermostat", "set:35")
    assert res_high["status"] == "error"
    assert "out of range" in res_high["reason"]

    # Malformed temperature
    res_bad = ha.execute_action("Thermostat", "set:abc")
    assert res_bad["status"] == "error"
    assert "invalid temperature" in res_bad["reason"]

    # Valid Fahrenheit (72F -> 22C)
    mock_ha = _MockHAHttpClient()
    ha_f = HomeAssistantAdapter(access_token="tok", http_client=mock_ha)
    res_f = ha_f.execute_action("Thermostat", "set:72F")
    assert res_f["status"] == "success"
    assert res_f["new_state"]["temperature"] == 22


def test_home_assistant_adapter_cover_open_close():
    mock_client = _MockHAHttpClient()
    ha = HomeAssistantAdapter(access_token="token", http_client=mock_client)

    res_open = ha.execute_action("Garage Door Opener", "open")
    assert res_open["status"] == "success"
    assert res_open["new_state"] == {"open": True}

    res_close = ha.execute_action("Garage Door Opener", "close")
    assert res_close["status"] == "success"
    assert res_close["new_state"] == {"open": False}


def test_home_assistant_adapter_edge_cases():
    ha = HomeAssistantAdapter(access_token="token")
    # Empty device
    assert ha.execute_action("", "on")["status"] == "error"
    # Empty action
    assert ha.execute_action("Kitchen Light", "")["status"] == "error"
    # Unsupported action
    res_bad_act = ha.execute_action("Kitchen Light", "explode")
    assert res_bad_act["status"] == "error"

    # Health check
    assert ha.health_check()["healthy"] is True
    assert ha.health_check()["adapter"] == "home_assistant"


def test_matter_bridge_window_covering():
    matter = MatterBridgeAdapter()

    res_open = matter.execute_action("Garage Door Opener", "open")
    assert res_open["status"] == "success"
    assert res_open["new_state"] == {"open": True}

    res_close = matter.execute_action("Garage Door Opener", "close")
    assert res_close["status"] == "success"
    assert res_close["new_state"] == {"open": False}


def test_matter_bridge_toggle_command():
    matter = MatterBridgeAdapter()

    res_on = matter.execute_action("Living Room Light", "on")
    assert res_on["new_state"] == {"power": "on"}

    res_toggle = matter.execute_action("Living Room Light", "toggle")
    assert res_toggle["status"] == "success"
    assert res_toggle["new_state"] == {"power": "off"}


def test_matter_bridge_temperature_range_and_edge_cases():
    matter = MatterBridgeAdapter()

    res_low = matter.execute_action("Thermostat", "set:8")
    assert res_low["status"] == "error"
    assert "out of range" in res_low["reason"]

    res_high = matter.execute_action("Thermostat", "set:40")
    assert res_high["status"] == "error"
    assert "out of range" in res_high["reason"]

    res_bad = matter.execute_action("Thermostat", "set:cold")
    assert res_bad["status"] == "error"

    # Valid Fahrenheit (72F -> 22C)
    res_f = matter.execute_action("Thermostat", "set:72F")
    assert res_f["status"] == "success"
    assert res_f["new_state"]["temperature"] == 22

    res_not_found = matter.execute_action("Nonexistent Device", "on")
    assert res_not_found["status"] == "error"
    assert "not found" in res_not_found["reason"]

    assert matter.health_check()["healthy"] is True
    assert matter.health_check()["protocol"] == "matter-1.3"


def test_end_to_end_active_adapter_dispatch(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    reset_active_adapter()

    # With default MockSQLiteAdapter, Kitchen Light starts off
    devs = devices.get_device_status_impl("Kitchen Light")
    assert devs[0]["state"]["power"] == "off"

    # Now switch active adapter to MatterBridgeAdapter
    matter = MatterBridgeAdapter()
    set_active_adapter(matter)

    try:
        # Calling devices.execute_device_action_impl now dispatches to MatterBridgeAdapter!
        res = devices.execute_device_action_impl("Living Room Light", "on")
        assert res["status"] == "success"
        assert res["adapter"] == "matter_bridge"
        assert res["new_state"] == {"power": "on"}

        # Memory was written
        recent = memory.recall_recent(limit=5)
        assert any("matter_bridge" in m["detail"] for m in recent)

        # Querying devices also retrieves from active adapter
        devs_matter = devices.get_device_status_impl("Living Room Light")
        assert len(devs_matter) == 1
        assert devs_matter[0]["state"]["power"] == "on"
        assert devs_matter[0]["id"] == "matter_living_room_light"
    finally:
        reset_active_adapter()

    assert get_active_adapter().name == "mock_sqlite"


def test_matter_bridge_subscribe_and_verify_attribute():
    matter = MatterBridgeAdapter()

    # Subscribe to OnOff attribute (0x0000) on Living Room Light
    sub_res = matter.subscribe_cluster_attribute(
        node_id="0x0000000000000010",
        endpoint_id=1,
        cluster_id=0x0006,
        attribute_id=0x0000,
    )
    assert sub_res["status"] == "success"
    sub_id = sub_res["subscription_id"]
    assert "sub_" in sub_id
    assert sub_res["subscription"]["status"] == "active"

    # Verify initial reported value (False = off)
    v_init = matter.verify_attribute_subscription(sub_id, expected_value=False)
    assert v_init["status"] == "success"
    assert v_init["verified"] is True
    assert v_init["current_value"] is False

    # Execute action to turn on
    matter.execute_action("Living Room Light", "on")

    # Verify updated attribute via subscription
    v_on = matter.verify_attribute_subscription(sub_id, expected_value=True)
    assert v_on["status"] == "success"
    assert v_on["verified"] is True
    assert v_on["current_value"] is True

    # Verify status reflects active subscription
    status = matter.get_status()
    assert status["subscription_verification_supported"] is True
    assert status["active_subscriptions_count"] == 1


def test_matter_bridge_subscribe_offline_or_unknown_node():
    matter = MatterBridgeAdapter()

    # Unknown node
    res_bad = matter.subscribe_cluster_attribute(
        node_id="0x99999999",
        endpoint_id=1,
        cluster_id=0x0006,
        attribute_id=0x0000,
    )
    assert res_bad["status"] == "error"

    # Nonexistent subscription verification
    v_bad = matter.verify_attribute_subscription("nonexistent_sub_123")
    assert v_bad["status"] == "error"


def test_home_assistant_websocket_connection_and_subscription():
    # Without token
    ha_no_token = HomeAssistantAdapter(access_token="")
    ws_unauth = ha_no_token.connect_websocket()
    assert ws_unauth["status"] == "error"
    assert ws_unauth["connected"] is False

    # With token
    ha = HomeAssistantAdapter(base_url="http://ha.local:8123", access_token="secret_token")
    assert ha.websocket_url == "ws://ha.local:8123/api/websocket"

    ws_auth = ha.connect_websocket()
    assert ws_auth["status"] == "connected"
    assert ws_auth["connected"] is True
    assert ws_auth["auth_status"] == "auth_ok"

    # Subscribe to entity state changes
    sub = ha.subscribe_state_changes("Kitchen Light")
    assert sub["status"] == "subscribed"
    assert sub["event_type"] == "state_changed"
    assert "light_kitchen_light" in sub["subscription_id"]

    # Verify status includes websocket endpoint
    status = ha.get_status()
    assert status["websocket_enabled"] is True
    assert status["endpoints"]["websocket"] == "ws://ha.local:8123/api/websocket"


def test_home_assistant_verify_state_via_websocket():
    mock_client = _MockHAHttpClient()
    ha = HomeAssistantAdapter(access_token="token", http_client=mock_client)

    # Initial state is off
    v_init = ha.verify_state_via_websocket("Kitchen Light", expected_state={"power": "off"})
    assert v_init["status"] == "success"
    assert v_init["verified"] is True
    assert v_init["transport"] == "websocket"

    # Execute action to turn on
    ha.execute_action("Kitchen Light", "on")

    # Verify state transition via websocket
    v_on = ha.verify_state_via_websocket("Kitchen Light", expected_state={"power": "on"})
    assert v_on["status"] == "success"
    assert v_on["verified"] is True
    assert v_on["actual_state"] == {"power": "on"}

    # Mismatch verification
    v_mismatch = ha.verify_state_via_websocket("Kitchen Light", expected_state={"power": "off"})
    assert v_mismatch["status"] == "failed"
    assert v_mismatch["verified"] is False


def test_matter_bridge_find_node_empty_or_whitespace_returns_none():
    matter = MatterBridgeAdapter()
    key1, node1 = matter._find_node("")
    assert key1 is None
    assert node1 is None

    key2, node2 = matter._find_node("   ")
    assert key2 is None
    assert node2 is None

    key3, node3 = matter._find_node(None)  # type: ignore
    assert key3 is None
    assert node3 is None


def test_matter_bridge_verify_subscription_mismatch_message():
    matter = MatterBridgeAdapter()
    sub_res = matter.subscribe_cluster_attribute(
        node_id="0x0000000000000010",
        endpoint_id=1,
        cluster_id=0x0006,
        attribute_id=0x0000,
    )
    sub_id = sub_res["subscription_id"]

    # Initial value is False (off), expect True to trigger mismatch
    v_mismatch = matter.verify_attribute_subscription(sub_id, expected_value=True)
    assert v_mismatch["status"] == "mismatch"
    assert v_mismatch["verified"] is False
    assert "mismatch" in v_mismatch["message"]


def test_matter_bridge_subscribe_unsupported_cluster_fails():
    matter = MatterBridgeAdapter()
    # Node 0x10 is a light (OnOff cluster 0x0006), attempt subscribing to Thermostat (0x0201)
    res = matter.subscribe_cluster_attribute(
        node_id="0x0000000000000010",
        endpoint_id=1,
        cluster_id=0x0201,
        attribute_id=0x0000,
    )
    assert res["status"] == "error"
    assert res["error_code"] == 0xC3
    assert "not supported" in res["message"]


def test_matter_bridge_simulate_offline():
    matter = MatterBridgeAdapter()
    # Node starts online
    assert matter.commissioned_nodes["living_room_light"]["online"] is True

    # Take offline
    res_off = matter.simulate_offline("Living Room Light", offline=True)
    assert res_off["online"] is False
    assert matter.commissioned_nodes["living_room_light"]["online"] is False

    # Action fails honestly
    act_res = matter.execute_action("Living Room Light", "on")
    assert act_res["status"] == "failed"
    assert "offline" in act_res["reason"]

    # Restore online
    res_on = matter.simulate_offline("Living Room Light", offline=False)
    assert res_on["online"] is True
    assert matter.commissioned_nodes["living_room_light"]["online"] is True


def test_home_assistant_verify_state_websocket_offline_device():
    mock_client = _MockHAHttpClient(entity_states={
        "light.kitchen_light": {
            "entity_id": "light.kitchen_light",
            "state": "unavailable",
            "attributes": {"friendly_name": "Kitchen Light"},
        }
    })
    ha = HomeAssistantAdapter(access_token="token", http_client=mock_client)

    v_off = ha.verify_state_via_websocket("Kitchen Light", expected_state={"power": "off"})
    assert v_off["status"] == "failed"
    assert v_off["verified"] is False
    assert v_off["reason"] == "device is offline"


def test_home_assistant_subscribe_unauthenticated_fails():
    ha = HomeAssistantAdapter(access_token="")
    sub = ha.subscribe_state_changes("Kitchen Light")
    assert sub["status"] == "error"
    assert sub["connected"] is False
    assert "Missing HA_ACCESS_TOKEN" in sub["reason"]


def test_home_assistant_simulate_offline():
    mock_client = _MockHAHttpClient()
    ha = HomeAssistantAdapter(access_token="token", http_client=mock_client)

    res_off = ha.simulate_offline("Kitchen Light", offline=True)
    assert res_off["online"] is False
    assert mock_client.entity_states["light.kitchen_light"]["state"] == "unavailable"

    # Action now fails because device is offline
    res_act = ha.execute_action("Kitchen Light", "on")
    assert res_act["status"] == "failed"
    assert "offline" in res_act["reason"]


def test_home_assistant_entity_not_found_fails_honestly():
    mock_client = _MockHAHttpClient()
    ha = HomeAssistantAdapter(access_token="token", http_client=mock_client)

    res = ha.execute_action("light.nonexistent_bulb", "on")
    assert res["status"] == "error"
    assert "not found" in res["reason"]


def test_simulate_offline_device_dispatches_to_active_adapter(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    reset_active_adapter()

    matter = MatterBridgeAdapter()
    set_active_adapter(matter)

    try:
        # Toggling offline via top-level simulate_offline_device_impl mutates active adapter
        res_off = devices.simulate_offline_device_impl("Living Room Light", offline=True)
        assert res_off["online"] is False
        assert matter.commissioned_nodes["living_room_light"]["online"] is False

        # Executing action fails with offline
        act_res = devices.execute_device_action_impl("Living Room Light", "on")
        assert act_res["status"] == "failed"
        assert "offline" in act_res["reason"]

        # Restore online
        res_on = devices.simulate_offline_device_impl("Living Room Light", offline=False)
        assert res_on["online"] is True
        assert matter.commissioned_nodes["living_room_light"]["online"] is True
    finally:
        reset_active_adapter()



