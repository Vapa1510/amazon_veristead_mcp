"""Amazon Replenishment Bridge (Capability Charter, Pillars 4 & 6).

Diagnoses unresponsive or failing smart-home hardware (e.g. dead battery
in smart lock, burned-out bulb in light fixture, depleted thermostat battery)
and generates a structured Amazon Cart replenishment proposal.

Never auto-orders: always presents an explicit, structured proposal
requiring human confirmation before purchase, adhering to Pillar 4
(Context-aware safety) and Pillar 6 (Low-friction confirmations).
"""
from __future__ import annotations

from veristead.tools.devices import _connection, _find_device, _row_to_dict
from veristead.tools.memory import remember

_REPLENISHMENT_CATALOG: dict[str, dict[str, str]] = {
    "lock": {
        "item_name": "Energizer CR123A Lithium 3V Batteries (2-Pack)",
        "asin": "B000IX214E",
        "price": "$9.98",
        "currency": "USD",
        "consumable_type": "battery",
        "estimated_delivery": "Tomorrow by 8 PM with Prime",
    },
    "light": {
        "item_name": "Philips Hue White A19 LED Smart Bulb (60W Equivalent)",
        "asin": "B084138MG9",
        "price": "$15.99",
        "currency": "USD",
        "consumable_type": "bulb",
        "estimated_delivery": "Tomorrow by 8 PM with Prime",
    },
    "thermostat": {
        "item_name": "Energizer Ultimate Lithium AAA Batteries (4-Pack)",
        "asin": "B00000J47L",
        "price": "$8.49",
        "currency": "USD",
        "consumable_type": "battery",
        "estimated_delivery": "Tomorrow by 8 PM with Prime",
    },
    "garage": {
        "item_name": "Energizer CR2032 3V Lithium Coin Batteries (4-Pack)",
        "asin": "B0002DSVS8",
        "price": "$6.25",
        "currency": "USD",
        "consumable_type": "battery",
        "estimated_delivery": "Tomorrow by 8 PM with Prime",
    },
    "plug": {
        "item_name": "Kasa Smart Plug Mini 15A Replacement Unit",
        "asin": "B07KVD8QXX",
        "price": "$12.99",
        "currency": "USD",
        "consumable_type": "hardware_unit",
        "estimated_delivery": "Tomorrow by 8 PM with Prime",
    },
}

_DEFAULT_REPLENISHMENT = {
    "item_name": "Amazon Basics Household Power Supply Unit",
    "asin": "B07GL2H3Y9",
    "price": "$14.99",
    "currency": "USD",
    "consumable_type": "power_supply",
    "estimated_delivery": "Tomorrow by 8 PM with Prime",
}


def _diagnose_device_issue(device_name: str, dtype: str, online: bool) -> str:
    """Provide a diagnostic root cause for offline/unresponsive devices."""
    if not online:
        if dtype == "lock":
            return f"Device '{device_name}' is offline/unresponsive. Suspected dead CR123A battery in Smart Lock."
        if dtype == "light":
            return f"Device '{device_name}' is offline/unresponsive. Suspected burned-out smart bulb or fixture power loss."
        if dtype == "thermostat":
            return f"Device '{device_name}' is offline/unresponsive. Suspected depleted backup battery."
        if dtype == "garage":
            return f"Device '{device_name}' is offline/unresponsive. Suspected dead coin-cell battery in opener/sensor."
        return f"Device '{device_name}' is offline/unresponsive. Suspected power failure or hardware fault."
    return f"Device '{device_name}' is currently operational. Preventive consumable replenishment proposal requested."


def propose_device_replenishment_impl(device: str) -> dict:
    """Diagnose device status and generate a structured Amazon Cart replenishment proposal.

    Follows Pillars 4 & 6:
    - Never auto-orders.
    - Returns structured proposal with ASIN, price, diagnosis, and spoken prompt.
    - Writes proposal to household memory for cross-session context.
    """
    if not device or not isinstance(device, str):
        return {"status": "error", "device": str(device), "reason": "device not found"}

    with _connection() as conn:
        row, error_reason = _find_device(conn, device)
        if row is None:
            return {"status": "error", "device": device, "reason": error_reason}
        current = _row_to_dict(row)

    device_name = current["name"]
    device_id = current["id"]
    dtype = current["type"]
    online = current["online"]

    item = _REPLENISHMENT_CATALOG.get(dtype, _DEFAULT_REPLENISHMENT)
    diagnosis = _diagnose_device_issue(device_name, dtype, online)

    message = (
        f"{diagnosis} Would you like me to add {item['item_name']} "
        f"({item['price']}) to your Amazon cart for {device_name}?"
    )

    remember(
        topic=f"replenishment:{device_name.lower()}",
        detail=f"Replenishment proposed for {device_name}: {item['item_name']} ({item['price']})",
    )

    return {
        "status": "proposed",
        "device": device_name,
        "device_id": device_id,
        "device_type": dtype,
        "online": online,
        "diagnosis": diagnosis,
        "replenishment": {
            "item_name": item["item_name"],
            "asin": item["asin"],
            "price": item["price"],
            "currency": item["currency"],
            "consumable_type": item["consumable_type"],
            "estimated_delivery": item["estimated_delivery"],
        },
        "action": "add_to_amazon_cart",
        "message": message,
        "requires_confirmation": True,
        "auto_ordered": False,
    }
