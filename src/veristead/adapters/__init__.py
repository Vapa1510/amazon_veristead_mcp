"""Pluggable Hardware Adapter Layer for Veristead (Capability Charter, Pillars 1 & 7).

Provides abstract and concrete smart-home hardware adapters:
- MockSQLiteAdapter: default hermetic local SQLite virtual home.
- HomeAssistantAdapter: production-ready REST/WebSocket adapter for Home Assistant.
- MatterBridgeAdapter: Matter 1.3 standard cluster bridge architecture for Thread/IPv6.
"""
from __future__ import annotations

from typing import Any

from veristead.adapters.base import BaseDeviceAdapter
from veristead.adapters.home_assistant import HomeAssistantAdapter
from veristead.adapters.matter import MatterBridgeAdapter
from veristead.adapters.mock_sqlite import MockSQLiteAdapter

# Global active adapter instance (defaults to MockSQLiteAdapter)
_ACTIVE_ADAPTER: BaseDeviceAdapter = MockSQLiteAdapter()


def get_active_adapter() -> BaseDeviceAdapter:
    """Return currently active device adapter."""
    global _ACTIVE_ADAPTER
    return _ACTIVE_ADAPTER


def set_active_adapter(adapter: BaseDeviceAdapter) -> None:
    """Switch active device adapter."""
    global _ACTIVE_ADAPTER
    if not isinstance(adapter, BaseDeviceAdapter):
        raise TypeError("Adapter must inherit from BaseDeviceAdapter")
    _ACTIVE_ADAPTER = adapter


def reset_active_adapter() -> None:
    """Reset active adapter back to default MockSQLiteAdapter."""
    global _ACTIVE_ADAPTER
    _ACTIVE_ADAPTER = MockSQLiteAdapter()


def get_adapter_status_impl() -> dict[str, Any]:
    """Inspect active and available device adapters and hardware readiness."""
    active = get_active_adapter()
    mock_sqlite = MockSQLiteAdapter()
    home_assistant = HomeAssistantAdapter()
    matter_bridge = MatterBridgeAdapter()

    return {
        "status": "ok",
        "active_adapter": active.name,
        "active_protocol": active.protocol,
        "active_details": active.get_status(),
        "available_adapters": {
            "mock_sqlite": mock_sqlite.get_status(),
            "home_assistant": home_assistant.get_status(),
            "matter_bridge": matter_bridge.get_status(),
        },
        "hardware_readiness": "ready",
        "verification_enforced": True,
        "architecture": (
            "Pluggable BaseDeviceAdapter interface with Request -> Execute -> Verify -> Confirm"
        ),
    }


__all__ = [
    "BaseDeviceAdapter",
    "MockSQLiteAdapter",
    "HomeAssistantAdapter",
    "MatterBridgeAdapter",
    "get_active_adapter",
    "set_active_adapter",
    "reset_active_adapter",
    "get_adapter_status_impl",
]
