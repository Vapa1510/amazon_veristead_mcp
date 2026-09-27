"""Mock SQLite Adapter for Veristead (Capability Charter, Pillars 1-4, 6).

Default, backward-compatible adapter that uses the local SQLite virtual home.
Ensures hermetic execution for tests, local MCP Inspector, and judge evaluations.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any

from veristead.adapters.base import BaseDeviceAdapter
from veristead.tools import devices


class MockSQLiteAdapter(BaseDeviceAdapter):
    """Hermetic SQLite virtual smart home adapter."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.custom_db_path = Path(db_path) if db_path else None

    @property
    def name(self) -> str:
        return "mock_sqlite"

    @property
    def protocol(self) -> str:
        return "sqlite-virtual-home"

    @property
    def active_db_path(self) -> Path:
        return self.custom_db_path or devices.DB_PATH

    @contextmanager
    def _use_db(self):
        if self.custom_db_path is not None:
            old_path = devices.DB_PATH
            devices.DB_PATH = self.custom_db_path
            try:
                yield
            finally:
                devices.DB_PATH = old_path
        else:
            yield

    def get_devices(self, name_or_room: str | None = None) -> list[dict[str, Any]]:
        """Return current status for matching devices via SQLite virtual home."""
        with self._use_db():
            return devices.get_device_status_impl(name_or_room)

    def get_room_devices(self, room: str) -> list[dict[str, Any]]:
        """Resolve a room name to its devices."""
        with self._use_db():
            return devices.get_room_devices_impl(room)

    def execute_action(self, device: str, action: str) -> dict[str, Any]:
        """Request -> Execute -> Verify -> Confirm on SQLite virtual home."""
        with self._use_db():
            return devices.execute_device_action_impl(device, action)

    def simulate_offline(self, device: str, offline: bool = True) -> dict[str, Any]:
        """Toggle device offline simulation."""
        with self._use_db():
            return devices.simulate_offline_device_impl(device, offline)

    def get_status(self) -> dict[str, Any]:
        """Return status and device count for the SQLite virtual home."""
        all_devs = self.get_devices()
        return {
            "adapter": "MockSQLiteAdapter",
            "name": self.name,
            "protocol": self.protocol,
            "connected": True,
            "ready": True,
            "status": "online",
            "device_count": len(all_devs),
            "online_device_count": sum(1 for d in all_devs if d.get("online")),
            "hermetic": True,
            "verification_enabled": True,
            "description": (
                "Hermetic SQLite virtual home mock for deterministic testing and judge evaluation"
            ),
        }
