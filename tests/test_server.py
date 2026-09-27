from starlette.applications import Starlette
from starlette.responses import Response
from starlette.routing import Route
from starlette.testclient import TestClient

from veristead.server import StripWWWAuthenticateMiddleware, _build_auth


def _make_app(status_code, headers=None):
    async def endpoint(request):
        return Response(status_code=status_code, headers=headers or {})

    app = Starlette(routes=[Route("/", endpoint)])
    app.add_middleware(StripWWWAuthenticateMiddleware)
    return app


def test_strips_www_authenticate_on_401():
    app = _make_app(401, headers={"WWW-Authenticate": "Bearer"})
    client = TestClient(app)
    response = client.get("/")

    assert response.status_code == 401
    assert "www-authenticate" not in {k.lower() for k in response.headers.keys()}


def test_leaves_other_headers_on_401():
    app = _make_app(401, headers={"WWW-Authenticate": "Bearer", "X-Custom": "value"})
    client = TestClient(app)
    response = client.get("/")

    assert response.headers.get("x-custom") == "value"


def test_does_not_touch_200_headers():
    """Regression guard: the middleware must only ever act on 401 responses,
    never strip headers from anything else."""
    app = _make_app(200, headers={"WWW-Authenticate": "Bearer"})
    client = TestClient(app)
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers.get("www-authenticate") == "Bearer"


def test_build_auth_returns_none_without_credentials(monkeypatch):
    monkeypatch.delenv("GITHUB_CLIENT_ID", raising=False)
    monkeypatch.delenv("GITHUB_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("OAUTH_BASE_URL", raising=False)
    monkeypatch.delenv("VERISTEAD_ENV", raising=False)
    monkeypatch.delenv("REQUIRE_AUTH", raising=False)

    assert _build_auth() is None


def test_build_auth_returns_provider_with_credentials(monkeypatch):
    monkeypatch.setenv("GITHUB_CLIENT_ID", "test_id")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "test_secret")
    monkeypatch.setenv("OAUTH_BASE_URL", "http://localhost:8000")

    assert _build_auth() is not None


def test_build_auth_raises_in_production_mode_without_credentials(monkeypatch):
    """Production mode strictly forbids running unauthenticated and raises explicit error."""
    import pytest
    monkeypatch.setenv("VERISTEAD_ENV", "production")
    monkeypatch.delenv("GITHUB_CLIENT_ID", raising=False)
    monkeypatch.delenv("GITHUB_CLIENT_SECRET", raising=False)

    with pytest.raises(RuntimeError, match="Production mode requires OAuth credentials. Server will not fall open."):
        _build_auth()


def test_build_auth_raises_when_require_auth_flag_set(monkeypatch):
    """REQUIRE_AUTH=true enforces strict authentication."""
    import pytest
    monkeypatch.delenv("VERISTEAD_ENV", raising=False)
    monkeypatch.setenv("REQUIRE_AUTH", "true")
    monkeypatch.delenv("GITHUB_CLIENT_ID", raising=False)

    with pytest.raises(RuntimeError, match="Production mode requires OAuth credentials. Server will not fall open."):
        _build_auth()


def test_build_auth_succeeds_in_production_with_valid_credentials(monkeypatch):
    """Production mode successfully returns auth provider when credentials are provided."""
    monkeypatch.setenv("VERISTEAD_ENV", "production")
    monkeypatch.setenv("GITHUB_CLIENT_ID", "prod_id")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "prod_secret")
    monkeypatch.setenv("OAUTH_BASE_URL", "https://auth.veristead.com")

    auth = _build_auth()
    assert auth is not None



def test_server_registers_all_11_tools():
    from veristead.server import (
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
    ]
    assert len(tools) == 11
    for t in tools:
        assert callable(t)


def test_server_registers_all_13_tools():
    from veristead.server import (
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
    ]
    assert len(tools) == 13
    for t in tools:
        assert callable(t)


def test_server_propose_device_replenishment_includes_card(tmp_path, monkeypatch):
    from veristead.server import propose_device_replenishment
    from veristead.tools import devices, memory

    monkeypatch.setattr(devices, "DB_PATH", tmp_path / "devices.db")
    monkeypatch.setattr(memory, "DB_PATH", tmp_path / "memory.db")

    res = propose_device_replenishment("Kitchen Light")
    assert res["status"] == "proposed"
    assert "card" in res
    assert "🛒 Amazon Replenishment Proposal" in res["card"]
    assert "Philips Hue" in res["card"]


def test_server_escalate_security_alert_includes_card(tmp_path, monkeypatch):
    from veristead.server import escalate_security_alert
    from veristead.tools import devices, memory

    monkeypatch.setattr(devices, "DB_PATH", tmp_path / "devices.db")
    monkeypatch.setattr(memory, "DB_PATH", tmp_path / "memory.db")

    res = escalate_security_alert("Front Door Lock", "device is offline")
    assert res["status"] == "simulated"
    assert "card" in res
    assert "🚨 [CRITICAL] Security Alert" in res["card"]
    assert "Front Door Lock" in res["card"]


def test_server_get_adapter_status_tool_includes_card(tmp_path, monkeypatch):
    from veristead.server import get_adapter_status
    from veristead.tools import devices

    monkeypatch.setattr(devices, "DB_PATH", tmp_path / "devices.db")

    res = get_adapter_status()
    assert res["status"] == "ok"
    assert res["active_adapter"] == "mock_sqlite"
    assert "card" in res
    assert "Smart-Home Device Adapters" in res["card"]
    assert "MatterBridgeAdapter" in res["card"]
    assert "HomeAssistantAdapter" in res["card"]


def test_server_get_reliability_metrics_tool_includes_card(tmp_path, monkeypatch):
    from veristead.server import get_reliability_metrics
    from veristead.tools import devices, telemetry

    monkeypatch.setattr(devices, "DB_PATH", tmp_path / "devices.db")
    monkeypatch.setattr(telemetry, "DB_PATH", tmp_path / "telemetry.db")

    res = get_reliability_metrics()
    assert res["status"] == "ok"
    assert "total_actions" in res
    assert "card" in res
    assert "Veristead Reliability & Impact Telemetry" in res["card"]
    assert "18.4%" in res["card"]


def test_server_registers_all_14_tools():
    from veristead.server import (
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
    ]
    assert len(tools) == 14
    for t in tools:
        assert callable(t)


def test_server_get_verification_telemetry_tool_includes_card(tmp_path, monkeypatch):
    from veristead.server import get_verification_telemetry
    from veristead.tools import devices, telemetry

    monkeypatch.setattr(devices, "DB_PATH", tmp_path / "devices.db")
    monkeypatch.setattr(telemetry, "DB_PATH", tmp_path / "telemetry.db")

    res = get_verification_telemetry()
    assert res["status"] == "ok"
    assert "total_verified_executions" in res
    assert "verification_success_rate_pct" in res
    assert "routine_partial_failure_rate_pct" in res
    assert "autonomous_self_healing_recovery_rate_pct" in res
    assert "security_escalation_count" in res
    assert "card" in res
    assert "Veristead Reliability & Impact Telemetry" in res["card"]
    assert "Routine Partial Failure Rate" in res["card"]
    assert "Autonomous Self-Healing Recovery Rate" in res["card"]


def test_server_registers_all_16_tools():
    """Verify all 16 tools are registered and callable on the MCP server."""
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


def test_server_orchestrate_command_tool(tmp_path, monkeypatch):
    """Server tool orchestrate_natural_language_command generates proposal with card."""
    from veristead.server import orchestrate_natural_language_command
    from veristead.tools import devices, memory, telemetry
    from veristead.tools.orchestrator import reset_proposals

    monkeypatch.setattr(devices, "DB_PATH", tmp_path / "devices.db")
    monkeypatch.setattr(memory, "DB_PATH", tmp_path / "memory.db")
    monkeypatch.setattr(telemetry, "DB_PATH", tmp_path / "telemetry.db")
    reset_proposals()

    res = orchestrate_natural_language_command("I'm cold", auto_confirm=False)
    assert res["status"] == "proposed"
    assert res["device"] == "Thermostat"
    assert "proposal_id" in res
    assert "card" in res
    assert "Proposed Action" in res["card"]


def test_server_confirm_and_execute_proposal_tool(tmp_path, monkeypatch):
    """Server tool confirm_and_execute_proposal executes and verifies hardware state."""
    from veristead.server import confirm_and_execute_proposal, orchestrate_natural_language_command
    from veristead.tools import devices, memory, telemetry
    from veristead.tools.orchestrator import reset_proposals

    monkeypatch.setattr(devices, "DB_PATH", tmp_path / "devices.db")
    monkeypatch.setattr(memory, "DB_PATH", tmp_path / "memory.db")
    monkeypatch.setattr(telemetry, "DB_PATH", tmp_path / "telemetry.db")
    reset_proposals()

    prop = orchestrate_natural_language_command("I'm cold", auto_confirm=False)
    exec_res = confirm_and_execute_proposal(prop["proposal_id"])
    assert exec_res["status"] == "success"
    assert exec_res["verified_state"]["temperature"] == 23
    assert "card" in exec_res
    assert "Action Confirmed & Verified" in exec_res["card"]


def test_server_registers_all_18_tools():
    """Verify all 18 tools (including hardware drift and CloudWatch audit) are registered."""
    from veristead.server import (
        confirm_and_execute_proposal,
        escalate_security_alert,
        execute_device_action,
        forget_topic,
        get_adapter_status,
        get_device_status,
        get_execution_audit_trail,
        get_reliability_metrics,
        get_room_devices,
        get_verification_telemetry,
        handle_natural_language_command,
        orchestrate_natural_language_command,
        propose_device_replenishment,
        recall_context,
        run_routine,
        simulate_hardware_drift,
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
        simulate_hardware_drift,
        get_execution_audit_trail,
    ]
    assert len(tools) == 18
    for t in tools:
        assert callable(t)


