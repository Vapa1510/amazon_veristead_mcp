"""Adapters tool exposure module.

Provides adapter status and inspection implementations for the MCP server.
"""
from __future__ import annotations

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
