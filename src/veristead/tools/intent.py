"""Bedrock-powered ambiguous-intent interpretation (Capability Charter, Pillar 4).

This is the ONLY place in the codebase that calls Bedrock, and it never
executes a device action itself. It interprets a natural-language request
into a specific (device, action) pair and returns a PROPOSAL. The caller
(Alexa+, or a human via MCP Inspector) is expected to confirm with the
user, then call execute_device_action directly to actually perform it --
which means the interpreted action still goes through the exact same
Request -> Execute -> Verify -> Confirm path every other action does.
Bedrock never bypasses the Verified Action Framework; it only ever feeds
into it.
"""
from __future__ import annotations

import json
import os
import re

import boto3
from botocore.config import Config

from veristead.tools.devices import _apply_action, get_device_status_impl

_SYSTEM_PROMPT = """You translate a natural-language smart-home request into
exactly one device action for the Veristead system.

You will be given the current list of devices (name, room, type, state,
online) and a natural-language command. Respond with ONLY a single JSON
object, no other text, in this exact shape:

{"device": "<exact device name>", "action": "<action string>", "message": "<one short spoken sentence proposing the change, to be confirmed by the user before it happens>"}

Action string rules, by device type:
- light or plug: "on" or "off"
- lock: "lock" or "unlock"
- garage: "open" or "close"
- thermostat: "set:<integer temperature>" (allowed range 10-32 C)

If the command doesn't clearly map to exactly one device and a valid
action, respond with ONLY:
{"error": "<short reason>"}

Never invent a device name that isn't in the provided list. Never invent
an action outside the rules above."""

def _strip_markdown_fences(raw_text: str) -> str:
    """Strip markdown code fences from model response using regex."""
    text = raw_text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


_bedrock_client = None


def _get_bedrock_client():
    """Reuse a single boto3 client (with hardened timeouts) across requests."""
    global _bedrock_client
    if _bedrock_client is None:
        region = os.getenv("AWS_REGION", "us-east-1")
        _bedrock_client = boto3.client(
            "bedrock-runtime",
            region_name=region,
            config=Config(
                connect_timeout=3,
                read_timeout=5,
                retries={"max_attempts": 2},
            ),
        )
    return _bedrock_client


def _parse_json_payload(raw_text: str) -> dict:
    """Parse model output, tolerating optional markdown code fences."""
    text = _strip_markdown_fences(raw_text)
    return json.loads(text)


def _validate_proposal(devices: list[dict], device_name: str, action: str) -> dict | None:
    """Return an error dict if the proposal is not executable against inventory."""
    if not device_name or not isinstance(device_name, str):
        return {
            "status": "error",
            "reason": "proposed device name is missing or invalid",
        }
    clean_name = device_name.strip().lower()
    matched = next(
        (
            d for d in devices
            if d["name"].lower() == clean_name
            or d["id"].lower() == clean_name
            or d["id"].lower() == clean_name.replace(" ", "_")
        ),
        None,
    )
    if matched is None:
        return {
            "status": "error",
            "reason": f"proposed device '{device_name}' is not in the household inventory",
        }
    if not action or not isinstance(action, str):
        return {
            "status": "error",
            "reason": "proposed action is missing or invalid",
        }
    if _apply_action(matched["state"], matched["type"], action) is None:
        return {
            "status": "error",
            "reason": (
                f"proposed action '{action}' is not valid for "
                f"{matched['name']} ({matched['type']})"
            ),
        }
    return None


def interpret_command_impl(command: str, client=None) -> dict:
    """Interpret a natural-language command into a proposed device action.

    Never executes anything -- always returns a proposal for confirmation.

    Args:
        command: the natural-language request, e.g. "I'm cold".
        client: optional pre-built boto3 bedrock-runtime client, used by
            tests to avoid a real AWS call.
    """
    model_id = os.getenv("BEDROCK_MODEL_ID")
    if not model_id:
        return {
            "status": "error",
            "reason": (
                "BEDROCK_MODEL_ID is not set -- copy the exact model ID from "
                "the Bedrock console's Model catalog into .env"
            ),
        }

    devices = get_device_status_impl()
    device_summary = [
        {
            "name": d["name"],
            "room": d["room"],
            "type": d["type"],
            "state": d["state"],
            "online": d["online"],
        }
        for d in devices
    ]

    bedrock = client or _get_bedrock_client()

    try:
        response = bedrock.converse(
            modelId=model_id,
            system=[{"text": _SYSTEM_PROMPT}],
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"text": f"Devices: {json.dumps(device_summary)}\n\nCommand: {command}"}
                    ],
                }
            ],
            inferenceConfig={"maxTokens": 300, "temperature": 0},
        )
    except Exception as exc:  # noqa: BLE001 -- surface any AWS/network error honestly
        return {"status": "error", "reason": f"Bedrock call failed: {exc}"}

    try:
        raw_text = response["output"]["message"]["content"][0]["text"]
        parsed = _parse_json_payload(raw_text)
    except (KeyError, IndexError, json.JSONDecodeError, TypeError) as exc:
        return {"status": "error", "reason": f"could not parse Bedrock's response: {exc}"}

    if "error" in parsed:
        return {"status": "error", "reason": parsed["error"]}

    if "device" not in parsed or "action" not in parsed:
        return {"status": "error", "reason": "Bedrock response missing device or action"}

    validation_error = _validate_proposal(devices, parsed["device"], parsed["action"])
    if validation_error is not None:
        return validation_error

    # Normalize to the canonical device name from inventory.
    canonical = next(
        d["name"] for d in devices if d["name"].lower() == parsed["device"].strip().lower()
    )

    return {
        "status": "proposed",
        "device": canonical,
        "action": parsed["action"].strip().lower(),
        "message": parsed.get("message", f"Set {canonical} to {parsed['action']}?"),
    }
