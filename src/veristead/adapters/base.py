"""Base interface for Veristead smart-home device adapters (Pillars 1 & 7).

Defines the pluggable adapter contract for real and simulated hardware:
all adapters must enforce Request -> Execute -> Verify -> Confirm.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseDeviceAdapter(ABC):
    """Abstract base adapter for smart-home device communication."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique adapter identifier (e.g. 'mock_sqlite', 'home_assistant', 'matter_bridge')."""
        pass

    @property
    @abstractmethod
    def protocol(self) -> str:
        """Communication protocol (e.g. 'sqlite-virtual-home', 'rest+websocket', 'matter-1.3')."""
        pass

    @abstractmethod
    def get_devices(self, name_or_room: str | None = None) -> list[dict[str, Any]]:
        """Retrieve current device states, optionally filtered by device name or room."""
        pass

    @abstractmethod
    def get_room_devices(self, room: str) -> list[dict[str, Any]]:
        """List every device in a given room."""
        pass

    @abstractmethod
    def execute_action(self, device: str, action: str) -> dict[str, Any]:
        """Execute an action on a device and verify its post-execution physical state.

        Follows Request -> Execute -> Verify -> Confirm:
        must re-read state after acting, and return a verified result.
        """
        pass

    @abstractmethod
    def get_status(self) -> dict[str, Any]:
        """Return connectivity, hardware readiness, and protocol capabilities."""
        pass

    def health_check(self) -> dict[str, Any]:
        """Perform a quick health and responsiveness check."""
        status = self.get_status()
        return {
            "adapter": self.name,
            "protocol": self.protocol,
            "healthy": status.get("connected", False) or status.get("ready", False),
            "status": status.get("status", "unknown"),
        }
