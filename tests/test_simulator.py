"""Tests for the Alexa+ Echo Show Visual Simulator UI and Web Endpoints."""
from __future__ import annotations

import json
from starlette.testclient import TestClient

from veristead.server import create_app
from veristead.tools import devices, memory, telemetry


def _setup_test_env(tmp_path, monkeypatch):
    """Seed clean SQLite databases for devices, memory, and telemetry."""
    monkeypatch.setattr(devices, "DB_PATH", tmp_path / "devices.db")
    monkeypatch.setattr(memory, "DB_PATH", tmp_path / "memory.db")
    monkeypatch.setattr(telemetry, "DB_PATH", tmp_path / "telemetry.db")
    from veristead.tools.orchestrator import reset_proposals
    reset_proposals()


def test_simulator_html_endpoint(tmp_path, monkeypatch):
    """GET /simulator serves the full Alexa Echo Show smart display HTML page."""
    _setup_test_env(tmp_path, monkeypatch)
    app = create_app()
    client = TestClient(app)

    response = client.get("/simulator")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    html = response.text

    # Verify Echo Show visual simulator components
    assert "Echo Show 10 • Veristead Smart Home" in html
    assert "Request → Execute → Verify → Confirm" in html
    assert "Silent Failures Prevented" in html
    assert "Household Devices" in html
    assert "Speak to Alexa" in html
    assert "deviceGrid" in html
    assert "cardMarkdownContent" in html
    assert "cardActionChips" in html


def test_ui_alias_endpoint(tmp_path, monkeypatch):
    """GET /ui is a mounted alias for the simulator."""
    _setup_test_env(tmp_path, monkeypatch)
    app = create_app()
    client = TestClient(app)

    response = client.get("/ui")
    assert response.status_code == 200
    assert "Echo Show 10 • Veristead Smart Home" in response.text


def test_root_endpoint_content_negotiation(tmp_path, monkeypatch):
    """GET / returns HTML for browser clients, or JSON info for API clients."""
    _setup_test_env(tmp_path, monkeypatch)
    app = create_app()
    client = TestClient(app)

    # Browser client requesting HTML
    resp_html = client.get("/", headers={"Accept": "text/html"})
    assert resp_html.status_code == 200
    assert "Echo Show 10" in resp_html.text

    # API client requesting JSON
    resp_json = client.get("/", headers={"Accept": "application/json"})
    assert resp_json.status_code == 200
    data = resp_json.json()
    assert data["name"] == "veristead-mcp"
    assert data["simulator_url"] == "/simulator"


def test_api_devices_endpoint(tmp_path, monkeypatch):
    """GET /api/devices returns all seeded smart-home devices."""
    _setup_test_env(tmp_path, monkeypatch)
    app = create_app()
    client = TestClient(app)

    response = client.get("/api/devices")
    assert response.status_code == 200
    data = response.json()
    assert "devices" in data
    assert len(data["devices"]) == 10

    device_names = [d["name"] for d in data["devices"]]
    assert "Living Room Light" in device_names
    assert "Kitchen Light" in device_names
    assert "Front Door Lock" in device_names
    assert "Garage Door Opener" in device_names
    assert "Thermostat" in device_names


def test_api_action_endpoint(tmp_path, monkeypatch):
    """POST /api/action executes and physically verifies a device action."""
    _setup_test_env(tmp_path, monkeypatch)
    app = create_app()
    client = TestClient(app)

    response = client.post("/api/action", json={"device": "Kitchen Light", "action": "on"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["new_state"]["power"] == "on"


def test_api_simulate_offline_and_honest_failure(tmp_path, monkeypatch):
    """POST /api/simulate_offline toggles offline state and enforces honest reporting."""
    _setup_test_env(tmp_path, monkeypatch)
    app = create_app()
    client = TestClient(app)

    # 1. Take Kitchen Light offline
    off_resp = client.post("/api/simulate_offline", json={"device": "Kitchen Light", "offline": True})
    assert off_resp.status_code == 200
    assert off_resp.json()["online"] is False

    # 2. Action on offline device reports honest failure
    act_resp = client.post("/api/action", json={"device": "Kitchen Light", "action": "on"})
    assert act_resp.status_code == 200
    act_data = act_resp.json()
    assert act_data["status"] == "failed"
    assert act_data["reason"] == "device is offline"

    # 3. Restore Kitchen Light online
    on_resp = client.post("/api/simulate_offline", json={"device": "Kitchen Light", "offline": False})
    assert on_resp.status_code == 200
    assert on_resp.json()["online"] is True


def test_api_routine_endpoint_returns_rich_card(tmp_path, monkeypatch):
    """POST /api/routine runs multi-device routine and returns consolidated result with card."""
    _setup_test_env(tmp_path, monkeypatch)
    app = create_app()
    client = TestClient(app)

    response = client.post("/api/routine", json={"routine": "movie time"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["routine"] == "movie time"
    assert "card" in data
    assert "Movie Time" in data["card"]["markdown"]
    assert "voice_speech" in data


def test_api_telemetry_endpoint(tmp_path, monkeypatch):
    """GET /api/telemetry returns quantitative reliability telemetry."""
    _setup_test_env(tmp_path, monkeypatch)
    app = create_app()
    client = TestClient(app)

    response = client.get("/api/telemetry")
    assert response.status_code == 200
    metrics = response.json()
    assert metrics["status"] == "ok"
    assert "total_verified_executions" in metrics
    assert "silent_failures_prevented" in metrics
    assert "verification_success_rate_pct" in metrics


def test_api_orchestrate_and_confirm_endpoints(tmp_path, monkeypatch):
    """Test full interactive voice command loop via /api/orchestrate and /api/confirm."""
    _setup_test_env(tmp_path, monkeypatch)
    app = create_app()
    client = TestClient(app)

    # 1. Send natural language voice command "I'm cold" (auto_confirm=False)
    orch_resp = client.post("/api/orchestrate", json={"command": "I'm cold", "auto_confirm": False})
    assert orch_resp.status_code == 200
    proposal = orch_resp.json()

    assert proposal["status"] == "proposed"
    assert proposal["device"] == "Thermostat"
    assert proposal["action"] == "set:23"
    assert "proposal_id" in proposal
    assert proposal["requires_confirmation"] is True
    assert "card" in proposal

    # Check that Thermostat was not mutated yet
    dev_status = devices.get_device_status_impl("Thermostat")
    assert dev_status[0]["state"]["temperature"] == 21

    # 2. Confirm and execute the proposal via /api/confirm
    prop_id = proposal["proposal_id"]
    confirm_resp = client.post("/api/confirm", json={"proposal_id": prop_id})
    assert confirm_resp.status_code == 200
    exec_data = confirm_resp.json()

    assert exec_data["status"] == "success"
    assert exec_data["verified_state"]["temperature"] == 23

    # Check that Thermostat state is now verified at 23
    dev_status_after = devices.get_device_status_impl("Thermostat")
    assert dev_status_after[0]["state"]["temperature"] == 23


def test_api_replenish_endpoint(tmp_path, monkeypatch):
    """POST /api/replenish generates Amazon cart replenishment proposal."""
    _setup_test_env(tmp_path, monkeypatch)
    app = create_app()
    client = TestClient(app)

    response = client.post("/api/replenish", json={"device": "Kitchen Light"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "proposed"
    assert "Philips Hue" in data["replenishment"]["item_name"]
    assert "card" in data
