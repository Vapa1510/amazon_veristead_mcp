"""Alexa+ Multi-Modal Echo Show Visual Simulator UI and Web Endpoints.

Provides a clean, responsive single-file HTML/CSS/JS dashboard simulating an
Amazon Echo Show 10/15 smart display:
- Real-time device tiles (living room, bedroom, kitchen, entryway, garage)
  reflecting SQLite state.
- Live voice-interaction bar (type or click sample voice commands like "I'm cold", "Good night").
- Multi-modal card display with clickable action chips ([Confirm & Execute], [Replenish Bulb], [Retry]).
- Real-time telemetry scorecard showing silent failures prevented and false confirmations eliminated.
"""
from __future__ import annotations

import json
from typing import Any

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse

from veristead.tools.cards import (
    format_device_status_card,
    format_replenishment_card,
    format_routine_result_card,
    format_telemetry_card,
)
from veristead.tools.devices import (
    execute_device_action_impl,
    get_device_status_impl,
    run_routine_impl,
    simulate_offline_device_impl,
)
from veristead.tools.orchestrator import (
    confirm_and_execute_proposal_impl,
    orchestrate_natural_language_command_impl,
)
from veristead.tools.replenishment import propose_device_replenishment_impl
from veristead.tools.telemetry import get_verification_telemetry_impl


def get_simulator_html() -> str:
    """Return the complete standalone HTML/CSS/JS Echo Show simulator page."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Veristead • Alexa+ Echo Show Smart Display Simulator</title>
  <style>
    :root {
      --bg: #090d16;
      --surface: #131b2e;
      --surface-card: #1c2640;
      --surface-hover: #263353;
      --border: #2a3756;
      --alexa-blue: #00caff;
      --alexa-dark: #007eb9;
      --text-main: #f8fafc;
      --text-muted: #94a3b8;
      --success: #10b981;
      --warning: #f59e0b;
      --danger: #ef4444;
      --badge-bg: #1e293b;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
    body { background: var(--bg); color: var(--text-main); min-height: 100vh; padding: 20px; display: flex; justify-content: center; }
    .show-bezel {
      width: 100%;
      max-width: 1400px;
      background: #0f172a;
      border: 8px solid #1e293b;
      border-radius: 28px;
      box-shadow: 0 25px 60px -15px rgba(0, 0, 0, 0.8), 0 0 40px rgba(0, 202, 255, 0.15);
      overflow: hidden;
      display: flex;
      flex-direction: column;
    }
    /* Echo Show Header */
    .show-header {
      background: linear-gradient(90deg, #0b1329 0%, #172554 100%);
      padding: 16px 28px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      border-bottom: 2px solid var(--border);
    }
    .alexa-brand {
      display: flex;
      align-items: center;
      gap: 12px;
      font-size: 1.15rem;
      font-weight: 700;
      letter-spacing: -0.02em;
    }
    .alexa-orb {
      width: 28px;
      height: 28px;
      border-radius: 50%;
      background: radial-gradient(circle, #00caff 0%, #007eb9 70%, #0284c7 100%);
      box-shadow: 0 0 16px var(--alexa-blue);
      animation: pulse-orb 2.5s infinite ease-in-out;
    }
    @keyframes pulse-orb {
      0%, 100% { transform: scale(1); box-shadow: 0 0 14px var(--alexa-blue); }
      50% { transform: scale(1.1); box-shadow: 0 0 22px #38bdf8; }
    }
    .header-meta {
      display: flex;
      align-items: center;
      gap: 20px;
      font-size: 0.88rem;
      color: var(--text-muted);
    }
    .header-badge {
      background: rgba(14, 165, 233, 0.15);
      border: 1px solid rgba(14, 165, 233, 0.4);
      color: #38bdf8;
      padding: 4px 10px;
      border-radius: 9999px;
      font-weight: 600;
    }

    /* Voice Bar */
    .voice-bar-section {
      background: #0f172a;
      padding: 18px 28px;
      border-bottom: 1px solid var(--border);
    }
    .voice-input-wrapper {
      display: flex;
      gap: 12px;
      align-items: center;
    }
    .voice-input {
      flex: 1;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 12px 18px;
      font-size: 1rem;
      color: var(--text-main);
      outline: none;
      transition: all 0.2s;
    }
    .voice-input:focus {
      border-color: var(--alexa-blue);
      box-shadow: 0 0 0 2px rgba(0, 202, 255, 0.2);
    }
    .btn-alexa {
      background: linear-gradient(135deg, var(--alexa-blue) 0%, var(--alexa-dark) 100%);
      color: #000;
      font-weight: 700;
      border: none;
      border-radius: 14px;
      padding: 12px 24px;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 8px;
      transition: transform 0.15s, opacity 0.15s;
    }
    .btn-alexa:hover { opacity: 0.95; transform: translateY(-1px); }
    .btn-alexa:active { transform: translateY(0); }
    .voice-chips {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-top: 12px;
    }
    .voice-chip {
      background: var(--surface-card);
      border: 1px solid var(--border);
      color: var(--text-muted);
      padding: 6px 14px;
      border-radius: 9999px;
      font-size: 0.82rem;
      cursor: pointer;
      transition: all 0.15s;
    }
    .voice-chip:hover {
      background: var(--surface-hover);
      color: var(--alexa-blue);
      border-color: var(--alexa-blue);
    }

    /* Main Grid: Devices (Left) & Alexa Surface (Right) */
    .show-body {
      display: grid;
      grid-template-columns: 1.15fr 0.85fr;
      gap: 20px;
      padding: 24px 28px;
      background: #090d16;
      flex: 1;
    }
    @media (max-width: 1024px) {
      .show-body { grid-template-columns: 1fr; }
    }

    /* Left Column: Device Tiles */
    .section-title {
      font-size: 1.05rem;
      font-weight: 700;
      color: var(--text-main);
      margin-bottom: 14px;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    .device-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
      gap: 14px;
    }
    .device-tile {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 10px;
      transition: border-color 0.2s, background 0.2s;
    }
    .device-tile.offline {
      border-color: rgba(239, 68, 68, 0.4);
      background: rgba(30, 20, 30, 0.6);
    }
    .tile-header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
    }
    .device-meta h4 {
      font-size: 0.96rem;
      font-weight: 700;
      color: #fff;
    }
    .device-meta p {
      font-size: 0.78rem;
      color: var(--text-muted);
      text-transform: capitalize;
    }
    .status-dot {
      display: inline-block;
      width: 10px;
      height: 10px;
      border-radius: 50%;
      background: var(--success);
      box-shadow: 0 0 8px var(--success);
    }
    .status-dot.offline {
      background: var(--danger);
      box-shadow: 0 0 8px var(--danger);
    }
    .tile-state {
      display: flex;
      align-items: center;
      gap: 8px;
      background: var(--surface-card);
      padding: 8px 12px;
      border-radius: 10px;
      font-size: 0.85rem;
      font-weight: 600;
    }
    .tile-controls {
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
    }
    .btn-tile {
      background: var(--surface-card);
      border: 1px solid var(--border);
      color: var(--text-main);
      padding: 6px 12px;
      border-radius: 8px;
      font-size: 0.78rem;
      cursor: pointer;
      font-weight: 600;
      transition: all 0.15s;
    }
    .btn-tile:hover {
      background: var(--surface-hover);
      border-color: var(--alexa-blue);
    }
    .btn-tile.danger {
      color: var(--danger);
      border-color: rgba(239, 68, 68, 0.4);
    }
    .btn-tile.danger:hover {
      background: rgba(239, 68, 68, 0.2);
    }

    /* Right Column: Multi-modal Card & Voice Output */
    .card-surface-container {
      display: flex;
      flex-direction: column;
      gap: 16px;
    }
    .voice-bubble {
      background: linear-gradient(135deg, rgba(14, 165, 233, 0.15) 0%, rgba(2, 132, 199, 0.1) 100%);
      border: 1px solid rgba(14, 165, 233, 0.35);
      border-radius: 16px;
      padding: 16px;
      display: flex;
      gap: 12px;
      align-items: flex-start;
    }
    .speech-icon { font-size: 1.4rem; }
    .speech-content h5 { font-size: 0.78rem; text-transform: uppercase; color: var(--alexa-blue); margin-bottom: 4px; }
    .speech-content p { font-size: 0.95rem; line-height: 1.4; color: #f1f5f9; font-weight: 500; }

    /* Visual Card Container */
    .echo-card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 18px;
      padding: 20px;
      min-height: 280px;
      display: flex;
      flex-direction: column;
      gap: 14px;
    }
    .card-header-bar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      border-bottom: 1px solid var(--border);
      padding-bottom: 10px;
    }
    .card-markdown {
      font-size: 0.88rem;
      line-height: 1.55;
      color: #e2e8f0;
      white-space: pre-wrap;
      max-height: 380px;
      overflow-y: auto;
      padding-right: 8px;
    }
    .card-markdown h1 { font-size: 1.15rem; color: #38bdf8; margin-bottom: 8px; }
    .card-markdown h2 { font-size: 1rem; color: #93c5fd; margin: 8px 0 4px; }
    .card-markdown h3 { font-size: 0.92rem; color: #bae6fd; margin: 6px 0 2px; }

    /* Interactive Action Chips Container */
    .card-actions {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-top: auto;
      padding-top: 14px;
      border-top: 1px solid var(--border);
    }
    .action-chip {
      background: var(--alexa-blue);
      color: #000;
      border: none;
      padding: 9px 16px;
      border-radius: 9999px;
      font-size: 0.85rem;
      font-weight: 700;
      cursor: pointer;
      transition: all 0.15s;
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }
    .action-chip:hover {
      background: #38bdf8;
      transform: translateY(-1px);
    }
    .action-chip.secondary {
      background: var(--surface-card);
      color: var(--text-main);
      border: 1px solid var(--border);
    }
    .action-chip.secondary:hover {
      background: var(--surface-hover);
      border-color: var(--alexa-blue);
    }
    .action-chip.warning {
      background: var(--warning);
      color: #000;
    }
    .action-chip.danger {
      background: var(--danger);
      color: #fff;
    }

    /* Telemetry Scorecard Section */
    .scorecard {
      background: #0f172a;
      border-top: 2px solid var(--border);
      padding: 20px 28px;
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 16px;
    }
    .metric-card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 14px 18px;
      display: flex;
      flex-direction: column;
      gap: 4px;
    }
    .metric-card.highlight {
      border-color: var(--alexa-blue);
      background: linear-gradient(135deg, rgba(0, 202, 255, 0.08) 0%, rgba(14, 165, 233, 0.02) 100%);
    }
    .metric-label { font-size: 0.76rem; text-transform: uppercase; color: var(--text-muted); font-weight: 600; }
    .metric-val { font-size: 1.5rem; font-weight: 800; color: #fff; }
    .metric-sub { font-size: 0.75rem; color: #38bdf8; }

    /* Toast */
    #toast {
      position: fixed;
      bottom: 24px;
      right: 24px;
      background: #1e293b;
      color: #fff;
      padding: 12px 20px;
      border-radius: 12px;
      border: 1px solid var(--alexa-blue);
      box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
      font-size: 0.88rem;
      opacity: 0;
      transform: translateY(20px);
      transition: all 0.3s;
      pointer-events: none;
      z-index: 1000;
    }
    #toast.show { opacity: 1; transform: translateY(0); }
  </style>
</head>
<body>
  <div class="show-bezel">
    <!-- Header -->
    <header class="show-header">
      <div class="alexa-brand">
        <div class="alexa-orb"></div>
        <span>Echo Show 10 • Veristead Smart Home</span>
      </div>
      <div class="header-meta">
        <span class="header-badge">Request → Execute → Verify → Confirm</span>
        <span id="liveClock">--:-- --</span>
      </div>
    </header>

    <!-- Voice Bar -->
    <div class="voice-bar-section">
      <div class="voice-input-wrapper">
        <input type="text" id="voiceInput" class="voice-input" placeholder="Alexa, I'm cold... (or type any smart-home command)" />
        <button id="sendVoiceBtn" class="btn-alexa" onclick="sendVoiceCommand()">
          <span>🎤 Speak to Alexa</span>
        </button>
      </div>
      <div class="voice-chips">
        <span class="voice-chip" onclick="quickVoice(&quot;I'm cold&quot;)">🗣️ &quot;I'm cold&quot;</span>
        <span class="voice-chip" onclick="quickVoice(&quot;Good night&quot;)">🌙 &quot;Good night&quot;</span>
        <span class="voice-chip" onclick="quickVoice(&quot;Movie time&quot;)">🎬 &quot;Movie time&quot;</span>
        <span class="voice-chip" onclick="quickVoice(&quot;Turn off the kitchen light&quot;)">💡 &quot;Turn off kitchen light&quot;</span>
        <span class="voice-chip" onclick="quickVoice(&quot;Simulate kitchen light offline&quot;)">⚡ &quot;Simulate offline&quot;</span>
        <span class="voice-chip" onclick="quickVoice(&quot;Replenish kitchen light&quot;)">🛒 &quot;Replenish bulb&quot;</span>
      </div>
    </div>

    <!-- Main Content Grid -->
    <div class="show-body">
      <!-- Left Column: Devices Grid -->
      <div>
        <div class="section-title">
          <span>🏠 Household Devices (SQLite Virtual Home)</span>
          <button class="btn-tile" onclick="fetchDevices()">🔄 Refresh</button>
        </div>
        <div class="device-grid" id="deviceGrid">
          <!-- Populated by JS -->
          <div style="color: var(--text-muted); font-size: 0.9rem;">Loading devices...</div>
        </div>
      </div>

      <!-- Right Column: Alexa+ Surface -->
      <div class="card-surface-container">
        <!-- Voice bubble -->
        <div class="voice-bubble">
          <div class="speech-icon">🗣️</div>
          <div class="speech-content">
            <h5>Alexa+ Spoken Audio</h5>
            <p id="alexaVoiceSpeech">"Welcome home. All smart devices are verified and operating normally."</p>
          </div>
        </div>

        <!-- MCP Visual Card -->
        <div class="echo-card">
          <div class="card-header-bar">
            <span style="font-weight: 700; font-size: 0.9rem; color: var(--alexa-blue);">📺 Echo Show Visual Surface (MCP Card)</span>
            <span id="cardStatusBadge" class="header-badge">Live</span>
          </div>
          <div class="card-markdown" id="cardMarkdownContent">
# 🏠 Smart Home Ready
Your verified smart-home execution layer is active.
- **Pillar 1:** Verified state re-read on every hardware action.
- **Pillar 2:** Honest partial-failure reporting instead of false 'Okay'.
- **Pillar 4:** Stateful Propose → Confirm → Execute loop.
          </div>
          <div class="card-actions" id="cardActionChips">
            <button class="action-chip" onclick="runRoutine(&quot;good night&quot;)">🌙 Run Good Night Routine</button>
            <button class="action-chip secondary" onclick="runRoutine(&quot;movie time&quot;)">🎬 Movie Time</button>
          </div>
        </div>
      </div>
    </div>

    <!-- Telemetry Scorecard -->
    <footer class="scorecard">
      <div class="metric-card highlight">
        <span class="metric-label">🛡️ Silent Failures Prevented</span>
        <span class="metric-val" id="metricSilent" style="color: #38bdf8;">0</span>
        <span class="metric-sub">Caught before false confirmation</span>
      </div>
      <div class="metric-card">
        <span class="metric-label">Total Verified Executions</span>
        <span class="metric-val" id="metricTotal">0</span>
        <span class="metric-sub">Physical state verified</span>
      </div>
      <div class="metric-card">
        <span class="metric-label">Verification Success Rate</span>
        <span class="metric-val" id="metricPassRate">100%</span>
        <span class="metric-sub" style="color: var(--success);">Zero false 'Okay'</span>
      </div>
      <div class="metric-card">
        <span class="metric-label">Self-Healing Compensations</span>
        <span class="metric-val" id="metricSelfHealing">0</span>
        <span class="metric-sub">Autonomous recovery</span>
      </div>
      <div class="metric-card">
        <span class="metric-label">Perimeter Security Escalations</span>
        <span class="metric-val" id="metricSecurity">0</span>
        <span class="metric-sub">AWS SNS dispatches</span>
      </div>
    </footer>
  </div>

  <div id="toast"></div>

  <script>
    function updateClock() {
      const now = new Date();
      document.getElementById('liveClock').textContent = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }
    setInterval(updateClock, 1000);
    updateClock();

    function showToast(msg) {
      const t = document.getElementById('toast');
      t.textContent = msg;
      t.classList.add('show');
      setTimeout(() => t.classList.remove('show'), 3500);
    }

    async function fetchDevices() {
      try {
        const res = await fetch('/api/devices');
        const data = await res.json();
        renderDevices(data.devices || []);
        fetchTelemetry();
      } catch (e) {
        console.error('Failed fetching devices:', e);
      }
    }

    function renderDevices(devices) {
      const grid = document.getElementById('deviceGrid');
      grid.innerHTML = '';

      devices.forEach(d => {
        const tile = document.createElement('div');
        tile.className = 'device-tile' + (d.online ? '' : ' offline');

        const iconMap = { light: '💡', plug: '🔌', lock: '🔒', garage: '🚪', cover: '🚪', thermostat: '🌡️' };
        const icon = iconMap[d.type] || '📦';

        let stateDisplay = '—';
        if (d.state) {
          if (d.state.power) stateDisplay = '⚡ Power: ' + d.state.power.toUpperCase();
          else if (d.state.temperature !== undefined) stateDisplay = '🌡️ Setpoint: ' + d.state.temperature + '°C';
          else if (d.state.locked !== undefined) stateDisplay = d.state.locked ? '🔐 LOCKED' : '🔓 UNLOCKED';
          else if (d.state.open !== undefined) stateDisplay = d.state.open ? '🚪 OPEN' : '🚪 CLOSED';
        }

        let controlsHtml = '';
        if (d.type === 'light' || d.type === 'plug') {
          controlsHtml = `
            <button class="btn-tile" onclick="executeAction('${d.name}', 'on')">On</button>
            <button class="btn-tile" onclick="executeAction('${d.name}', 'off')">Off</button>
          `;
        } else if (d.type === 'lock') {
          controlsHtml = `
            <button class="btn-tile" onclick="executeAction('${d.name}', 'lock')">Lock</button>
            <button class="btn-tile" onclick="executeAction('${d.name}', 'unlock')">Unlock</button>
          `;
        } else if (d.type === 'garage' || d.type === 'cover') {
          controlsHtml = `
            <button class="btn-tile" onclick="executeAction('${d.name}', 'open')">Open</button>
            <button class="btn-tile" onclick="executeAction('${d.name}', 'close')">Close</button>
          `;
        } else if (d.type === 'thermostat') {
          const curTemp = d.state?.temperature || 21;
          controlsHtml = `
            <button class="btn-tile" onclick="executeAction('${d.name}', 'set:${curTemp - 1}')">-1°C</button>
            <button class="btn-tile" onclick="executeAction('${d.name}', 'set:${curTemp + 1}')">+1°C</button>
          `;
        }

        controlsHtml += `
          <button class="btn-tile ${d.online ? 'danger' : ''}" style="margin-left: auto;" onclick="toggleOffline('${d.name}', ${d.online})">
            ${d.online ? 'Take Offline' : 'Restore'}
          </button>
        `;

        tile.innerHTML = `
          <div class="tile-header">
            <div class="device-meta">
              <h4>${icon} ${d.name}</h4>
              <p>${d.room} • ${d.type}</p>
            </div>
            <span class="status-dot ${d.online ? '' : 'offline'}" title="${d.online ? 'Online' : 'Offline'}"></span>
          </div>
          <div class="tile-state">${stateDisplay}</div>
          <div class="tile-controls">${controlsHtml}</div>
        `;
        grid.appendChild(tile);
      });
    }

    async function executeAction(device, action) {
      try {
        const res = await fetch('/api/action', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ device, action })
        });
        const result = await res.json();
        showToast(result.status === 'success' ? `✅ ${device} verified ${action}` : `❌ ${device} failed: ${result.reason}`);
        fetchDevices();
      } catch (e) {
        showToast('Error executing action');
      }
    }

    async function toggleOffline(device, isCurrentlyOnline) {
      try {
        await fetch('/api/simulate_offline', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ device, offline: isCurrentlyOnline })
        });
        showToast(`⚡ ${device} is now ${isCurrentlyOnline ? 'OFFLINE' : 'ONLINE'}`);
        fetchDevices();
      } catch (e) {
        showToast('Error toggling offline');
      }
    }

    async function runRoutine(name) {
      try {
        const res = await fetch('/api/routine', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ routine: name })
        });
        const result = await res.json();
        handleResultCard(result);
        fetchDevices();
      } catch (e) {
        showToast('Error running routine');
      }
    }

    async function sendVoiceCommand() {
      const inp = document.getElementById('voiceInput');
      const cmd = inp.value.trim();
      if (!cmd) return;
      inp.value = '';

      try {
        const res = await fetch('/api/orchestrate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ command: cmd, auto_confirm: false })
        });
        const result = await res.json();
        handleResultCard(result);
        fetchDevices();
      } catch (e) {
        showToast('Error orchestrating voice command');
      }
    }

    function quickVoice(text) {
      document.getElementById('voiceInput').value = text;
      sendVoiceCommand();
    }

    function handleResultCard(data) {
      const speech = data.voice_speech || data.message || (data.card && data.card.voice_speech) || "Command processed.";
      document.getElementById('alexaVoiceSpeech').textContent = `"${speech}"`;

      let md = '';
      let actions = [];

      if (data.card) {
        if (typeof data.card === 'string') {
          md = data.card;
        } else {
          md = data.card.markdown || '';
          actions = data.card.interactive_actions || [];
        }
      } else if (data.summary) {
        md = `# Routine: ${data.routine}\\n\\n**Status:** ${data.status}\\n**Summary:** ${data.summary}`;
      } else if (data.reason) {
        md = `# ❌ Error\\n\\n${data.reason}`;
      }

      document.getElementById('cardMarkdownContent').innerText = md;
      renderActionChips(actions);
      showToast(speech);
    }

    function renderActionChips(actions) {
      const container = document.getElementById('cardActionChips');
      container.innerHTML = '';

      if (!actions || actions.length === 0) {
        container.innerHTML = `
          <button class="action-chip" onclick="runRoutine(&quot;good night&quot;)">🌙 Run Good Night Routine</button>
          <button class="action-chip secondary" onclick="runRoutine(&quot;movie time&quot;)">🎬 Movie Time</button>
        `;
        return;
      }

      actions.forEach(a => {
        const btn = document.createElement('button');
        btn.className = `action-chip ${a.style || ''}`;
        btn.textContent = a.label;
        btn.onclick = () => handleChipClick(a);
        container.appendChild(btn);
      });
    }

    async function handleChipClick(actionObj) {
      const { tool, parameters } = actionObj;
      try {
        let endpoint = '';
        let body = {};

        if (tool === 'confirm_and_execute_proposal') {
          endpoint = '/api/confirm';
          body = { proposal_id: parameters.proposal_id };
        } else if (tool === 'propose_device_replenishment') {
          endpoint = '/api/replenish';
          body = { device: parameters.device };
        } else if (tool === 'execute_device_action') {
          endpoint = '/api/action';
          body = { device: parameters.device, action: parameters.action };
        } else if (tool === 'run_routine') {
          endpoint = '/api/routine';
          body = { routine: parameters.routine_name };
        } else if (tool === 'get_device_status') {
          fetchDevices();
          showToast('Refreshed smart home devices.');
          return;
        }

        if (endpoint) {
          const res = await fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
          });
          const result = await res.json();
          handleResultCard(result);
          fetchDevices();
        }
      } catch (e) {
        showToast('Error handling action chip: ' + e);
      }
    }

    async function fetchTelemetry() {
      try {
        const res = await fetch('/api/telemetry');
        const m = await res.json();
        document.getElementById('metricSilent').textContent = m.silent_failures_prevented || 0;
        document.getElementById('metricTotal').textContent = m.total_verified_executions || m.total_actions || 0;
        document.getElementById('metricPassRate').textContent = (m.verification_success_rate_pct || 100.0) + '%';
        document.getElementById('metricSelfHealing').textContent = m.compensations_executed || 0;
        document.getElementById('metricSecurity').textContent = m.security_escalation_count || m.security_escalations_dispatched || 0;
      } catch (e) {
        console.error('Failed fetching telemetry:', e);
      }
    }

    // Initial load
    fetchDevices();
  </script>
</body>
</html>
"""


# ── Web Route Handlers ───────────────────────────────────────────────────

async def simulator_view(request: Request) -> HTMLResponse:
    """Serve the single-file Alexa Echo Show simulator dashboard."""
    return HTMLResponse(get_simulator_html())


async def index_view(request: Request) -> HTMLResponse | JSONResponse:
    """Root route: returns visual simulator for browser, or JSON status for API clients."""
    accept = request.headers.get("accept", "")
    if "text/html" in accept or "*/*" in accept or not accept:
        return HTMLResponse(get_simulator_html())
    return JSONResponse({
        "name": "veristead-mcp",
        "description": "Verified smart-home execution layer for Alexa+",
        "simulator_url": "/simulator",
        "status": "online",
    })


async def api_get_devices(request: Request) -> JSONResponse:
    """Return all devices and status."""
    devices = get_device_status_impl()
    return JSONResponse({"devices": devices})


async def api_post_action(request: Request) -> JSONResponse:
    """Execute device action and return verified result."""
    body = await request.json()
    device = body.get("device", "")
    action = body.get("action", "")
    res = execute_device_action_impl(device, action)
    return JSONResponse(res)


async def api_post_routine(request: Request) -> JSONResponse:
    """Run routine and return consolidated result with card."""
    body = await request.json()
    routine = body.get("routine", "")
    res = run_routine_impl(routine)
    card = format_routine_result_card(res)
    res["card"] = card.to_dict() if hasattr(card, "to_dict") else card
    res["voice_speech"] = card.voice_speech if hasattr(card, "voice_speech") else ""
    return JSONResponse(res)


async def api_post_simulate_offline(request: Request) -> JSONResponse:
    """Toggle device offline simulation."""
    body = await request.json()
    device = body.get("device", "")
    offline = body.get("offline", True)
    res = simulate_offline_device_impl(device, offline)
    return JSONResponse(res)


async def api_get_telemetry(request: Request) -> JSONResponse:
    """Return quantitative reliability telemetry metrics."""
    metrics = get_verification_telemetry_impl()
    return JSONResponse(metrics)


async def api_post_orchestrate(request: Request) -> JSONResponse:
    """Orchestrate natural language command end-to-end."""
    body = await request.json()
    command = body.get("command", "")
    auto_confirm = body.get("auto_confirm", False)
    res = orchestrate_natural_language_command_impl(command, auto_confirm=auto_confirm)
    if "card" in res and hasattr(res["card"], "to_dict"):
        res["card"] = res["card"].to_dict()
    return JSONResponse(res)


async def api_post_confirm(request: Request) -> JSONResponse:
    """Confirm and execute pending proposal."""
    body = await request.json()
    proposal_id = body.get("proposal_id", "")
    res = confirm_and_execute_proposal_impl(proposal_id)
    if "card" in res and hasattr(res["card"], "to_dict"):
        res["card"] = res["card"].to_dict()
    return JSONResponse(res)


async def api_post_replenish(request: Request) -> JSONResponse:
    """Propose Amazon replenishment for a device."""
    body = await request.json()
    device = body.get("device", "")
    res = propose_device_replenishment_impl(device)
    card = format_replenishment_card(res)
    res["card"] = card.to_dict() if hasattr(card, "to_dict") else card
    res["voice_speech"] = card.voice_speech if hasattr(card, "voice_speech") else ""
    return JSONResponse(res)


def register_simulator_routes(app: Any) -> None:
    """Mount Echo Show simulator and REST API routes on the Starlette application."""
    app.add_route("/simulator", simulator_view, methods=["GET"])
    app.add_route("/ui", simulator_view, methods=["GET"])
    app.add_route("/", index_view, methods=["GET"])
    app.add_route("/api/devices", api_get_devices, methods=["GET"])
    app.add_route("/api/action", api_post_action, methods=["POST"])
    app.add_route("/api/routine", api_post_routine, methods=["POST"])
    app.add_route("/api/simulate_offline", api_post_simulate_offline, methods=["POST"])
    app.add_route("/api/telemetry", api_get_telemetry, methods=["GET"])
    app.add_route("/api/orchestrate", api_post_orchestrate, methods=["POST"])
    app.add_route("/api/confirm", api_post_confirm, methods=["POST"])
    app.add_route("/api/replenish", api_post_replenish, methods=["POST"])
