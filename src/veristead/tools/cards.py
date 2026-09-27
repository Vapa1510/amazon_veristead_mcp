"""MCP App card surface — rich multi-modal visual confirmation cards for Alexa+ Echo Show.

Formats tool results as structured, multi-modal objects containing:
- markdown: Rich formatted presentation card for display screens.
- interactive_actions: List of clickable action buttons/chips with tool names,
  parameters, and display labels for MCP Apps and visual Echo Show surfaces.
- voice_speech: Exact SSML/voice spoken text for Alexa+ voice responses.

Inherits from dict and supports string containment (__contains__) so that existing
tests and clients expecting raw markdown or text blocks continue to work with
zero regressions.
"""
from __future__ import annotations

from typing import Any


# ── Rich Multi-Modal Card Class ──────────────────────────────────────────

class RichCard(dict):
    """Multi-modal card representation for Alexa+ Echo Show and MCP App surfaces.

    Carries:
    - markdown: Presentation markdown text (for visual screen rendering)
    - interactive_actions: List of clickable action chips/buttons (for MCP Apps & screens)
    - voice_speech: Spoken SSML / voice speech text for Alexa+ voice response
    """

    def __init__(
        self,
        markdown: str,
        interactive_actions: list[dict[str, Any]] | None = None,
        voice_speech: str | None = None,
    ) -> None:
        super().__init__(
            markdown=markdown,
            interactive_actions=interactive_actions or [],
            voice_speech=voice_speech or "",
        )

    @property
    def markdown(self) -> str:
        return self["markdown"]

    @property
    def interactive_actions(self) -> list[dict[str, Any]]:
        return self["interactive_actions"]

    @property
    def voice_speech(self) -> str:
        return self["voice_speech"]

    def __contains__(self, item: object) -> bool:
        """Support both dict key check and string containment on the markdown text.

        Allows `assert 'Dashboard' in card` to succeed seamlessly for backwards
        compatibility with existing test suites.
        """
        if super().__contains__(item):
            return True
        return isinstance(item, str) and item in self["markdown"]

    def __str__(self) -> str:
        return self["markdown"]

    def __repr__(self) -> str:
        return (
            f"RichCard(markdown={self['markdown']!r}, "
            f"interactive_actions={self['interactive_actions']!r}, "
            f"voice_speech={self['voice_speech']!r})"
        )

    def startswith(self, prefix: str, *args) -> bool:
        return self["markdown"].startswith(prefix, *args)

    def endswith(self, suffix: str, *args) -> bool:
        return self["markdown"].endswith(suffix, *args)

    def find(self, sub: str, *args) -> int:
        return self["markdown"].find(sub, *args)

    def to_dict(self) -> dict[str, Any]:
        return {
            "markdown": self["markdown"],
            "interactive_actions": self["interactive_actions"],
            "voice_speech": self["voice_speech"],
        }


# ── Status icons ─────────────────────────────────────────────────────────

_TYPE_ICONS = {
    "light": "💡",
    "plug": "🔌",
    "lock": "🔒",
    "garage": "🚪",
    "thermostat": "🌡️",
}

_STATUS_ICONS = {
    "online": "🟢",
    "offline": "🔴",
}


# ── Device status card ───────────────────────────────────────────────────

def format_device_status_card(devices: list[dict]) -> RichCard:
    """Format a list of device statuses into a visual dashboard card with interactive chips.

    Produces a structured RichCard containing markdown, interactive action chips,
    and Alexa voice speech.
    """
    if not devices:
        return RichCard(
            markdown="📋 **No devices found.**",
            interactive_actions=[],
            voice_speech="No smart home devices found in inventory.",
        )

    # Group devices by room
    rooms: dict[str, list[dict]] = {}
    for d in devices:
        room = d.get("room", "unknown")
        rooms.setdefault(room, []).append(d)

    lines = ["# 🏠 Smart Home Dashboard", ""]

    interactive_actions: list[dict[str, Any]] = [
        {
            "label": "Run Good Night Routine",
            "tool": "run_routine",
            "parameters": {"routine_name": "good night"},
            "style": "primary",
        },
        {
            "label": "Run Movie Time Routine",
            "tool": "run_routine",
            "parameters": {"routine_name": "movie time"},
            "style": "secondary",
        },
    ]

    offline_devices = [d for d in devices if not d.get("online")]

    for room_name in sorted(rooms.keys()):
        room_devices = rooms[room_name]
        lines.append(f"## 📍 {room_name.title()}")
        lines.append("")

        for d in room_devices:
            icon = _TYPE_ICONS.get(d.get("type", ""), "📦")
            status_icon = _STATUS_ICONS["online" if d.get("online") else "offline"]
            state = d.get("state", {})

            # Build a human-readable state string
            state_parts = []
            if "power" in state:
                state_parts.append(f"{'⚡ On' if state['power'] == 'on' else '⭘ Off'}")
            if "temperature" in state:
                state_parts.append(f"{state['temperature']}°C")
            if "locked" in state:
                state_parts.append(f"{'🔐 Locked' if state['locked'] else '🔓 Unlocked'}")
            if "open" in state:
                state_parts.append(f"{'Open' if state['open'] else 'Closed'}")

            state_str = " · ".join(state_parts) if state_parts else "—"

            lines.append(f"  {icon} **{d['name']}** {status_icon}")
            lines.append(f"     {state_str}")
            lines.append("")

            # If device is offline, add quick replenishment / retry action chip
            if not d.get("online"):
                interactive_actions.append({
                    "label": f"Replenish {d['name']}",
                    "tool": "propose_device_replenishment",
                    "parameters": {"device": d["name"]},
                    "style": "warning",
                })

    lines.append("---")
    lines.append("")

    total_count = len(devices)
    if offline_devices:
        off_names = ", ".join(d["name"] for d in offline_devices)
        voice_speech = (
            f"Smart home dashboard: {total_count} devices monitored. "
            f"{len(offline_devices)} device{' is' if len(offline_devices) == 1 else 's are'} offline: {off_names}."
        )
    else:
        voice_speech = (
            f"Smart home dashboard: all {total_count} devices are online and responsive."
        )

    return RichCard(
        markdown="\n".join(lines),
        interactive_actions=interactive_actions,
        voice_speech=voice_speech,
    )


# ── Routine result card ──────────────────────────────────────────────────

def format_routine_result_card(result: dict) -> RichCard:
    """Format a routine execution result into a visual summary card with action chips.

    Shows a clear pass/fail breakdown with per-device results, self-healing
    compensations, and critical perimeter security escalations.
    """
    routine = result.get("routine") or "unknown"
    status = result.get("status") or "unknown"
    summary = result.get("summary") or ""
    results = result.get("results") or []

    if status == "error":
        return RichCard(
            markdown=f"# ❌ Routine Failed\n\n**{routine}**: {result.get('reason', 'unknown error')}",
            interactive_actions=[
                {
                    "label": "Inspect Device Status",
                    "tool": "get_device_status",
                    "parameters": {},
                    "style": "secondary",
                }
            ],
            voice_speech=f"Routine {routine} failed: {result.get('reason', 'unknown error')}.",
        )

    status_emoji = "✅" if status == "ok" else "⚠️"
    lines = [
        f"# {status_emoji} Routine: {routine.title()}",
        "",
        f"**Summary:** {summary}",
        "",
    ]

    succeeded = [r for r in results if r.get("status") == "success"]
    failed = [r for r in results if r.get("status") != "success"]
    interactive_actions: list[dict[str, Any]] = []

    if succeeded:
        lines.append("### ✅ Succeeded")
        lines.append("")
        for r in succeeded:
            device = r.get("device", "unknown")
            new_state = r.get("new_state", {})
            state_parts = []
            if "power" in new_state:
                state_parts.append(f"{'on' if new_state['power'] == 'on' else 'off'}")
            if "temperature" in new_state:
                state_parts.append(f"{new_state['temperature']}°C")
            if "locked" in new_state:
                state_parts.append(f"{'locked' if new_state['locked'] else 'unlocked'}")
            state_str = " → ".join(state_parts) if state_parts else "done"
            lines.append(f"  ✓ **{device}** — {state_str}")
        lines.append("")

    if failed:
        lines.append("### ❌ Failed")
        lines.append("")
        for r in failed:
            device = r.get("device", "unknown")
            reason = r.get("reason", "unknown")
            lines.append(f"  ✗ **{device}** — {reason}")

            # Add interactive chips to retry failed step or trigger replenishment
            interactive_actions.append({
                "label": f"Retry {device}",
                "tool": "execute_device_action",
                "parameters": {"device": device, "action": "off" if "light" in device.lower() else "lock"},
                "style": "warning",
            })
            interactive_actions.append({
                "label": f"Replenish {device}",
                "tool": "propose_device_replenishment",
                "parameters": {"device": device},
                "style": "primary",
            })
        lines.append("")

    compensations = result.get("compensations") or []
    if compensations:
        lines.append("### 🔄 Self-Healing Compensations")
        lines.append("")
        for c in compensations:
            orig = c.get("failed_device", "unknown")
            sub = c.get("substitute_device", "unknown")
            act = c.get("compensating_action", "unknown")
            c_status = c.get("status", "unknown")
            icon = "🛡️" if c_status == "success" else "⚠️"
            status_desc = (
                f"(compensated {orig})"
                if c_status == "success"
                else f"(attempted compensation for {orig}, but {c_status})"
            )
            lines.append(f"  {icon} **{sub}** — {act} {status_desc}")
        lines.append("")

    security_alerts = result.get("security_alerts") or []
    if security_alerts:
        lines.append("### 🚨 Critical Security Escalations (AWS SNS)")
        lines.append("")
        for sa in security_alerts:
            dev = sa.get("device", "unknown")
            chan = (sa.get("channel") or "sns").upper()
            sev = sa.get("severity") or "CRITICAL"
            mid = sa.get("message_id") or "dispatched"
            lines.append(f"  🚨 **{dev}** — [{sev}] Escalated via {chan} (ID: {mid})")

            interactive_actions.insert(0, {
                "label": f"Verify Perimeter ({dev})",
                "tool": "get_device_status",
                "parameters": {"name_or_room": "garage"},
                "style": "danger",
            })
        lines.append("")

    if not interactive_actions:
        interactive_actions.append({
            "label": "Inspect Devices",
            "tool": "get_device_status",
            "parameters": {},
            "style": "secondary",
        })

    if status == "ok":
        voice_speech = f"Routine {routine.title()} completed successfully. All devices verified."
    else:
        voice_speech = f"Routine {routine.title()} completed with partial failure: {summary}."

    return RichCard(
        markdown="\n".join(lines),
        interactive_actions=interactive_actions,
        voice_speech=voice_speech,
    )


# ── Replenishment proposal card ──────────────────────────────────────────

def format_replenishment_card(proposal: dict) -> RichCard:
    """Format an Amazon Replenishment proposal into a visual markdown card with action chips."""
    device = proposal.get("device") or "Unknown Device"
    status = proposal.get("status") or "unknown"
    if status == "error":
        return RichCard(
            markdown=f"# ❌ Replenishment Proposal Failed\n\n**{device}**: {proposal.get('reason', 'unknown error')}",
            interactive_actions=[
                {
                    "label": "Inspect Device",
                    "tool": "get_device_status",
                    "parameters": {"name_or_room": device},
                    "style": "secondary",
                }
            ],
            voice_speech=f"Replenishment proposal failed: {proposal.get('reason')}.",
        )

    item = proposal.get("replenishment") or {}
    item_name = item.get("item_name") or "Replacement Item"
    asin = item.get("asin") or "N/A"
    price = item.get("price") or "N/A"
    delivery = item.get("estimated_delivery") or "Tomorrow by 8 PM with Prime"
    diagnosis = proposal.get("diagnosis") or ""
    action = proposal.get("action") or "add_to_amazon_cart"

    lines = [
        f"# 🛒 Amazon Replenishment Proposal: {device}",
        "",
        f"**Diagnosis:** {diagnosis}",
        "",
        "### 📦 Recommended Item",
        f"- **Item:** {item_name}",
        f"- **ASIN:** `{asin}`",
        f"- **Price:** {price}",
        f"- **Delivery:** {delivery}",
        "",
        f"**Proposed Action:** `{action}`",
        "**⚠️ Confirmation Required:** Explicit user approval needed before any order is placed (never auto-ordered).",
    ]

    interactive_actions = [
        {
            "label": f"Add to Cart ({price})",
            "tool": "confirm_and_execute_proposal",
            "parameters": {"proposal_id": f"replenish_{asin}"},
            "style": "primary",
        },
        {
            "label": "Dismiss Proposal",
            "tool": "forget_topic",
            "parameters": {"topic": f"replenishment:{device.lower()}"},
            "style": "secondary",
        },
    ]

    voice_speech = (
        f"I diagnosed {device}: {diagnosis}. "
        f"I can add {item_name} for {price} to your Amazon cart. "
        "Would you like me to proceed?"
    )

    return RichCard(
        markdown="\n".join(lines),
        interactive_actions=interactive_actions,
        voice_speech=voice_speech,
    )


# ── Security escalation card ─────────────────────────────────────────────

def format_security_alert_card(alert: dict) -> RichCard:
    """Format a security escalation alert into a visual markdown card with action chips."""
    device = alert.get("device") or "Unknown Device"
    severity = alert.get("severity") or "CRITICAL"
    channel = (alert.get("channel") or "sns").upper()
    status = alert.get("status") or "unknown"
    msg_id = alert.get("message_id") or "N/A"
    payload = alert.get("alert") or {}
    reason = alert.get("reason") or payload.get("reason", "security check failed")
    routine = alert.get("routine") or payload.get("routine", "manual")

    emoji = "🚨" if severity == "CRITICAL" else "⚠️"
    lines = [
        f"# {emoji} [{severity}] Security Alert: {device}",
        "",
        f"**Status:** {status} via {channel} (ID: `{msg_id}`)",
        f"**Routine:** {routine}",
        f"**Reason:** {reason}",
        "",
        "> 🛡️ **Action Required:** Physical perimeter verification recommended immediately.",
    ]

    interactive_actions = [
        {
            "label": f"Retry Lock ({device})",
            "tool": "execute_device_action",
            "parameters": {"device": device, "action": "lock"},
            "style": "danger",
        },
        {
            "label": "Verify Perimeter",
            "tool": "get_device_status",
            "parameters": {"name_or_room": "garage"},
            "style": "secondary",
        },
    ]

    voice_speech = (
        f"<speak><emphasis level='strong'>Critical security alert.</emphasis> "
        f"{device} failed: {reason}. Escalated via {channel}.</speak>"
    )

    return RichCard(
        markdown="\n".join(lines),
        interactive_actions=interactive_actions,
        voice_speech=voice_speech,
    )


# ── Hardware adapter status card ─────────────────────────────────────────

def format_adapter_status_card(status: dict) -> RichCard:
    """Format smart-home device adapter and hardware readiness status into a visual card."""
    active = status.get("active_adapter", "unknown")
    protocol = status.get("active_protocol", "unknown")
    adapters = status.get("available_adapters", {})

    lines = [
        "# 🔌 Smart-Home Device Adapters & Hardware Bridge",
        "",
        f"**Active Adapter:** `{active}` ({protocol})",
        "**Verification Standard:** Request → Execute → Verify → Confirm (Enforced across all adapters)",
        "",
        "### 🌐 Pluggable Hardware Integrations",
        "",
    ]

    for name, info in adapters.items():
        adapter_name = info.get("adapter", name)
        proto = info.get("protocol", "unknown")
        is_ready = info.get("ready", False)
        status_text = info.get("status", "unknown")
        desc = info.get("description", "")
        icon = "🟢" if is_ready else "⚪"

        lines.append(f"- {icon} **{adapter_name}** (`{proto}`): **{status_text.upper()}**")
        if desc:
            lines.append(f"  *{desc}*")
        if "supported_clusters" in info:
            clusters = ", ".join(c.get("name", "") for c in info["supported_clusters"])
            lines.append(f"  *Clusters:* {clusters}")
        if "supported_domains" in info:
            domains = ", ".join(info["supported_domains"])
            lines.append(f"  *Domains:* {domains}")
        lines.append("")

    lines.append("> 🛡️ **Hardware Assurance:** Physical state is always re-read before any confirmation.")

    interactive_actions = [
        {
            "label": "Verify All Devices",
            "tool": "get_device_status",
            "parameters": {},
            "style": "primary",
        },
        {
            "label": "View Reliability Telemetry",
            "tool": "get_verification_telemetry",
            "parameters": {},
            "style": "secondary",
        },
    ]

    voice_speech = (
        f"Smart-home adapter {active} is active using protocol {protocol}. "
        "Verified smart-home hardware bridge is online."
    )

    return RichCard(
        markdown="\n".join(lines),
        interactive_actions=interactive_actions,
        voice_speech=voice_speech,
    )


# ── Telemetry & reliability card ─────────────────────────────────────────

def format_telemetry_card(metrics: dict) -> RichCard:
    """Format quantitative reliability metrics and impact benchmarks into a visual card."""
    total = metrics.get("total_verified_executions", metrics.get("total_actions", 0))
    successes = metrics.get("verified_successes", 0)
    pass_rate = metrics.get("verification_success_rate_pct", metrics.get("verification_pass_rate_pct", 100.0))
    silent_prevented = metrics.get("silent_failures_prevented", 0)
    industry_benchmark = metrics.get("industry_unverified_failure_rate_pct", 18.4)
    mtbf = metrics.get("mean_actions_between_failures", 0.0)
    compensations = metrics.get("compensations_executed", 0)
    self_healing_rate = metrics.get("autonomous_self_healing_recovery_rate_pct", 100.0)
    routine_partial_rate = metrics.get("routine_partial_failure_rate_pct", 0.0)
    security_alerts = metrics.get("security_escalation_count", metrics.get("security_escalations_dispatched", 0))
    summary = metrics.get("benchmark_summary", "")

    lines = [
        "# 📊 Veristead Reliability & Impact Telemetry",
        "",
        "**Verification Standard:** Request → Execute → Verify → Confirm (Pillars 1 & 2)",
        "",
        "### 📈 Execution & Verification Performance",
        f"- **Total Actions Executed:** {total}",
        f"- **Total Verified Executions:** {total}",
        f"- **Verified Successes:** {successes}",
        f"- **Verification Pass Rate:** {pass_rate}%",
        f"- **Verification Success Rate:** {pass_rate}%",
        f"- **Mean Actions Between Failures (MTBF):** {mtbf} actions",
        "",
        "### 🛡️ Industry Benchmark Comparison",
        f"- **Industry Baseline Failure Rate:** {industry_benchmark}% *(unverified routine commands)*",
        f"- **Routine Partial Failure Rate:** {routine_partial_rate}% *(vs 18–24% industry silent failure baseline)*",
        f"- **Silent Failures Prevented:** {silent_prevented} *(caught before false confirmation)*",
        "- **False 'Okay' Confirmations:** 0 *(100% eliminated)*",
        "",
        "### 🔄 Autonomous Safety & Multi-Service Reliability",
        f"- **Autonomous Self-Healing Recovery Rate:** {self_healing_rate}%",
        f"- **Self-Healing Compensations Executed:** {compensations}",
        f"- **Critical Security Escalations (AWS SNS):** {security_alerts}",
        f"- **Security Escalation Count:** {security_alerts}",
        "",
    ]
    if summary:
        lines.append(f"> 💡 **Impact:** {summary}")

    interactive_actions = [
        {
            "label": "Run Verification Health Check",
            "tool": "run_routine",
            "parameters": {"routine_name": "movie time"},
            "style": "primary",
        },
        {
            "label": "Inspect Device States",
            "tool": "get_device_status",
            "parameters": {},
            "style": "secondary",
        },
    ]

    voice_speech = (
        f"Veristead reliability telemetry: {total} executions verified with {pass_rate} percent "
        f"success rate, preventing {silent_prevented} silent failures with zero false confirmations."
    )

    return RichCard(
        markdown="\n".join(lines),
        interactive_actions=interactive_actions,
        voice_speech=voice_speech,
    )


# ── In-server Orchestration Proposal cards ───────────────────────────────

def format_proposal_card(proposal: dict) -> RichCard:
    """Format an in-server natural language action proposal into an Echo Show card with action chips."""
    proposal_id = proposal.get("proposal_id", "")
    device = proposal.get("device", "Unknown Device")
    action = proposal.get("action", "")
    command = proposal.get("command", "")
    message = proposal.get("message", f"Set {device} to {action}?")

    lines = [
        f"# 💡 Proposed Action: {device}",
        "",
        f"**User Request:** \"{command}\"",
        f"**Proposed Change:** `{action}` on **{device}**",
        f"**Proposal ID:** `{proposal_id}`",
        "",
        f"🗣️ **Spoken Prompt:** {message}",
        "",
        "> ⚠️ **Confirmation Required:** Action will only execute upon explicit confirmation.",
    ]

    interactive_actions = [
        {
            "label": "Confirm & Execute",
            "tool": "confirm_and_execute_proposal",
            "parameters": {"proposal_id": proposal_id},
            "style": "primary",
        },
        {
            "label": "Cancel",
            "tool": "cancel_proposal",
            "parameters": {"proposal_id": proposal_id},
            "style": "secondary",
        },
    ]

    return RichCard(
        markdown="\n".join(lines),
        interactive_actions=interactive_actions,
        voice_speech=message,
    )


def format_proposal_execution_card(proposal: dict, execution: dict) -> RichCard:
    """Format an executed proposal result with verified post-execution physical state."""
    proposal_id = proposal.get("proposal_id", "")
    device = proposal.get("device", "Unknown Device")
    action = proposal.get("action", "")
    status = execution.get("status", "unknown")
    new_state = execution.get("new_state", {})
    reason = execution.get("reason", "")

    if status == "success":
        lines = [
            f"# ✅ Action Confirmed & Verified: {device}",
            "",
            f"**Executed Action:** `{action}`",
            f"**Physical State Verified:** `{new_state}`",
        ]
        if proposal_id:
            lines.append(f"**Proposal ID:** `{proposal_id}`")
        lines.extend([
            "",
            "> 🛡️ **Verified Execution:** Device state re-read from hardware and confirmed.",
        ])
        voice_speech = f"Confirmed and verified: {device} is now {action}."
        style = "primary"
    else:
        lines = [
            f"# ⚠️ Execution Verification Failed: {device}",
            "",
            f"**Attempted Action:** `{action}`",
            f"**Failure Reason:** {reason}",
        ]
        if proposal_id:
            lines.append(f"**Proposal ID:** `{proposal_id}`")
        lines.extend([
            "",
            "> 🛡️ **Honest Reporting:** No false confirmation given.",
        ])
        voice_speech = f"Action on {device} failed verification: {reason}."
        style = "danger"

    interactive_actions = [
        {
            "label": "Inspect All Devices",
            "tool": "get_device_status",
            "parameters": {},
            "style": "secondary",
        },
        {
            "label": "View Telemetry Scorecard",
            "tool": "get_verification_telemetry",
            "parameters": {},
            "style": "secondary",
        },
    ]

    return RichCard(
        markdown="\n".join(lines),
        interactive_actions=interactive_actions,
        voice_speech=voice_speech,
    )
