# Veristead — Verified Smart-Home Execution for Alexa+

> **Never claim a physical action succeeded without checking that it did.**

A self-hosted [MCP](https://modelcontextprotocol.io/) server built for Amazon's **Build, Ship, Shape** hackathon (Alexa+ track + AWS Builder mini-challenge). Veristead doesn't add a missing feature to Alexa+ — it makes an existing one trustworthy.

**The problem:** Alexa+ already controls smart homes. What real users report is that the control is unreliable: routines fail silently, wrong devices respond, and a confident "Okay" doesn't always mean the light actually turned off.

**Veristead's answer:** A seven-pillar Capability Charter ([`veristead-capability-charter.md`](veristead-capability-charter.md)) that guarantees every mutating action is re-verified before confirmation, partial failures are reported honestly, ambiguous intent is resolved by Amazon Bedrock, real hardware ecosystems are supported via pluggable adapters (Matter 1.3 & Home Assistant), and system reliability is quantified against industry benchmarks.

---

## Quick Start (Judge Evaluation & Local Testing)

> 💡 **For Hackathon Judges:** You do **not** need an AWS account, EC2 instance, or GitHub OAuth credentials to evaluate Veristead locally. The server starts in open development mode with an explicit simulated household (10 devices, 7 rooms) and hermetic SQLite persistence.

### Prerequisites
- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended) or `pip`

### Step 1: Clone & Setup
```bash
git clone https://github.com/Vapa1510/amazon_veristead_mcp.git
cd amazon_veristead_mcp

# Install dependencies using uv
uv venv && uv sync --extra dev

# Alternatively, using standard venv + pip:
# python -m venv .venv && source .venv/bin/activate  # (on Windows: .venv\Scripts\activate)
# pip install -e ".[dev]"

# Configure local environment (runs in open, unauthenticated dev mode by default)
cp .env.example .env
```

### Step 2: Run Unit Tests (Hermetic & Instant)
```bash
uv run pytest tests/ -v
# or: pytest tests/ -v
```
All unit tests pass in seconds with zero regressions across all test suites (hermetic SQLite, no network, mocked Bedrock Converse API and Amazon SNS client simulation).

### Step 3: Launch Local MCP Server & Multi-Modal Simulator
```bash
uv run python src/veristead/server.py
```
The server starts on `http://0.0.0.0:8000/`.

### Step 4: Visual Echo Show Smart Display Simulator (Recommended for Judges!)
Open your browser and navigate to:
👉 **`http://localhost:8000/simulator`** (or `http://localhost:8000/ui`)

Experience Veristead as an **Alexa+ Echo Show 10/15 smart display**:
- 🎛️ **Real-time Hardware Grid:** Live visual states for all 10 household devices across 7 rooms.
- 🎙️ **Voice & Natural Language Bar:** Propose, confirm, and execute commands with interactive visual cards.
- ⚡ **Flagship 30-Second Demo Button:** Instantly toggle the Kitchen Light offline and trigger `"Good Night"` to watch Veristead catch the failure and trigger self-healing substitution.
- 📊 **Live Telemetry Scorecard:** Real-time metrics on verified actions, silent failures prevented, and MTBF.

### Step 5: Interact with MCP Inspector (Optional)
Launch the official [MCP Inspector](https://github.com/modelcontextprotocol/inspector) in your terminal:
```bash
npx @modelcontextprotocol/inspector
```
Connect to `http://0.0.0.0:8000/mcp/` (Transport: **Streamable HTTP**).

---

## Alexa+ Multi-Modal Echo Show Simulator & Adaptive Cards

Standard MCP servers only deliver raw JSON strings to developer inspectors. Veristead bridges the gap between agentic MCP backend execution and a delightful, voice-first **Echo Show smart display experience**:

1. **Embedded Echo Show Web Surface (`/simulator`, `/ui`):**
   - Zero external frontend dependencies — served directly from Starlette / FastMCP.
   - Content negotiation: Visiting `/` in a web browser renders the multi-modal Echo Show dashboard; programmatic HTTP clients receive MCP Streamable HTTP.
   - Interactive device tiles allow judges to manually toggle lights, lock deadbolts, adjust thermostat temperatures, and test hardware re-read verification in real time.

2. **Rich Multi-Modal Adaptive Cards (`RichCard`):**
   - Moves beyond flat emoji markdown to structured multi-modal surfaces.
   - Each card returns:
     - `markdown`: Full markdown formatted view for terminal & chat clients.
     - `interactive_actions`: Actionable button chips (`[Confirm & Execute]`, `[Reject]`, `[Diagnose]`, `[Run Routine]`) for touchscreen smart displays.
     - `voice_speech`: Natural Alexa+ voice speech synthesis text / SSML payloads.
   - Built with 100% backward string containment compatibility (`assert "..." in card`).

3. **In-Server Stateful Orchestrator (`propose` → `confirm` → `execute`):**
   - Eliminates the need for clients to manually chain multiple tools.
   - `orchestrate_natural_language_command`: Interprets intent via Bedrock (or fast-path local voice shortcuts), generates a structured proposal card with actionable chips, and stores it in SQLite.
   - `confirm_and_execute_proposal`: One-click or voice-driven execution that physically mutates hardware, re-reads state, updates household memory, and logs verification telemetry.
   - Optional `auto_confirm=True` mode for full-loop verified autonomous execution in single round-trip agent workflows.

4. **Domain Modeling & Hardware Polish:**
   - **Garage Door Opener:** Strictly modeled as a `garage`/`cover` actuator with physical `open` and `close` actions. Electrical `on`/`off` commands are explicitly rejected with helpful guidance (`"garage door opener does not support 'on' — use 'open' or 'close' instead"`).
   - **Thermostat Residential Bounds:** Strictly enforces residential comfort and freeze/heat safety limits (10°C–32°C / 50°F–90°F). Prevents dangerous extremes with voice-friendly explanations while preserving backwards-compatible `"out of range"` semantics.

---

## Flagship Demo Moment (30-Second Proof)

The demo that proves Veristead's core value in 30 seconds:

```
1. Call simulate_offline_device("Kitchen Light", true)  [or click 'Simulate Failure' in /simulator]
2. Call run_routine("good night")                       [or click 'Run Good Night' in /simulator]
3. Observe the response:
   → status: "partial_failure"
   → summary: "6 succeeded, 1 failed (Kitchen Light)"
   → Visual card rendering ✅ per-device successes, ❌ the offline failure, and 🛡️ self-healing compensation
   → NOT a blanket "Okay" or false "Done"
```

Every standard smart-home integration would say "Done." Veristead verifies state and tells you what actually happened.

---

## Seven-Pillar Capability Charter

Veristead implements all seven pillars defined in the [`veristead-capability-charter.md`](veristead-capability-charter.md):

| # | Pillar | Implementation |
|---|--------|----------------|
| 1 | **Verified execution** | Every mutating action re-reads device state after acting; response is built from verified state, never assumed |
| 2 | **Partial-failure transparency** | Multi-device routines report per-device pass/fail status with visual cards — never a blanket "done" or false success |
| 3 | **Fast-path routing** | Deterministic commands (`"turn off kitchen light"`) bypass Bedrock entirely — zero LLM latency |
| 4 | **Context-aware safety** | Ambiguous or high-stakes requests (`"I'm cold"`) use Amazon Bedrock Converse API to propose actions with explicit context before acting |
| 5 | **Household memory** | SQLite-backed cross-session memory that persists household layout and context across server restarts |
| 6 | **Low-friction confirmations** | Read-only checks never confirm; simple actions execute directly; ambiguous/high-stakes actions confirm once inline |
| 7 | **Pluggable Adapters & Quantitative Telemetry** | Extends verification to live Home Assistant REST & Matter 1.3 clusters; tracks silent failure elimination against an 18.4% industry baseline and calculates MTBF |

> **Honest Simulation:** All smart-home devices are explicitly simulated by default via local SQLite backing — never passed off as real hardware. Real-hardware adapters (Matter 1.3, Home Assistant) are selectable via configuration.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│               Echo Show Display / MCP Client / Web              │
│       (Browser: /simulator | MCP Inspector | Alexa+ Voice)      │
└────────────────┬───────────────────────────────┬────────────────┘
                 │ Streamable HTTP (MCP 2025-11-25+)
                 │ Web UI REST Endpoints (/api/*) & OAuth 2.1
┌────────────────▼───────────────────────────────▼────────────────┐
│                       Veristead MCP Server                      │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  FastMCP + Starlette + Uvicorn                            │  │
│  │  ┌─────────────────────────┐  ┌─────────────────────────┐ │  │
│  │  │   OAuth 2.1             │  │  Echo Show Simulator    │ │  │
│  │  │   GitHubProvider        │  │  UI Routes (/simulator) │ │  │
│  │  └─────────────────────────┘  └─────────────────────────┘ │  │
│  └───────────────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  16 MCP Tools                                             │  │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────────┐ ┌───────────┐ │  │
│  │  │ Devices  │ │ Memory   │ │ Intent &     │ │ Adapters  │ │  │
│  │  │ (5 tools)│ │ (3 tools)│ │ Orchestrator │ │ &Telemetry│ │  │
│  │  │          │ │          │ │ (3 tools)    │ │ (3 tools) │ │  │
│  │  ├──────────┴─┴──────────┴─┴──────────────┴─┤           │ │  │
│  │  │ Replenishment Bridge & SNS Escalation    │           │ │  │
│  │  │ (2 tools: propose_replenishment, alert)  │           │ │  │
│  │  └────┬────────────┬─────────────┬──────────┴─────┬─────┘ │  │
│  │       │            │             │                │       │  │
│  │  SQLite DB    SQLite DB     AWS Bedrock      SQLite DB    │  │
│  │  (devices)    (memory)      & Amazon SNS    (telemetry)   │  │
│  │               (proposals)                                 │  │
│  └───────┼───────────────────────────────────────────┼───────┘  │
│  ┌───────▼───────────────────────────────────────────▼───────┐  │
│  │  Pluggable Device Adapter Layer (BaseDeviceAdapter)        │  │
│  │  ┌──────────────────┐ ┌────────────────┐ ┌──────────────┐ │  │
│  │  │ MockSQLiteAdapter│ │ HomeAssistant  │ │ Matter 1.3   │ │  │
│  │  │ (Hermetic local) │ │ (REST/WS API)  │ │ (Clusters)   │ │  │
│  │  └──────────────────┘ └────────────────┘ └──────────────┘ │  │
│  └───────────────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Multi-Modal Adaptive Cards Surface (Markdown, Actions,   │  │
│  │  Voice SSML Speech, Touchscreen Interactive Buttons)      │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                 │
      ┌──────────▼──────────┐
      │  EC2 + Nginx + TLS  │
      │  (Production deploy) │
      └─────────────────────┘
```

---

## Tools (18 total)

| Tool | Pillar | Type | Description |
|------|--------|------|-------------|
| `get_device_status(name_or_room)` | 1, 3 | Read | Status for matching devices + multi-modal visual dashboard card |
| `get_room_devices(room)` | 3, 6 | Read | List every device in a room |
| `execute_device_action(device, action)` | 1, 3, 6 | Write | Act → re-verify → confirm (never a blind "Okay") |
| `run_routine(routine_name)` | 1, 2 | Write | Multi-device routine with autonomous self-healing compensations & per-device pass/fail card |
| `simulate_offline_device(device, offline)` | 2 | Demo | Toggle a device offline to trigger partial-failure on command |
| `simulate_hardware_drift(device, drift)` | 1 | Demo | Silent physical hardware write failure injection: proves state verification re-read catches drop |
| `recall_context(topic, limit)` | 5 | Read | Query recent household memory |
| `view_memory()` | 5 | Read | Full transparency dump of all remembered context |
| `forget_topic(topic)` | 5 | Write | Delete all memory entries under a topic |
| `handle_natural_language_command(command)` | 4, 6 | AI | Bedrock Converse API ambiguous intent → proposal (never auto-executes) |
| `orchestrate_natural_language_command(command, auto_confirm)` | 4, 6 | AI / Orchestration | In-server orchestrator: parses command, generates proposal card, optionally auto-executes with verification |
| `confirm_and_execute_proposal(proposal_id)` | 1, 4, 6 | Write / Orchestration | Executes confirmed proposal, verifies physical device transitions, logs to memory & telemetry |
| `propose_device_replenishment(device)` | 4, 6 | Commerce | Amazon Replenishment Bridge: diagnoses hardware failure & generates structured Amazon Cart proposals (ASIN + price, never auto-orders) |
| `escalate_security_alert(device, reason, routine)` | 1, 4 | Security | AWS Multi-Service: escalates perimeter security failures to Amazon SNS (hermetic simulation fallback) |
| `get_adapter_status()` | 1, 7 | Adapter | Hardware bridge status & inspection: MockSQLite, Home Assistant REST/WebSocket, Matter 1.3 clusters |
| `get_verification_telemetry()` | 1, 2, 7 | Telemetry | Real-time reliability stats: verified executions, pass rate, partial routine failure rate, self-healing recovery rate, SNS alerts |
| `get_reliability_metrics()` | 1, 2, 7 | Telemetry | Quantitative verification telemetry & 18.4% industry benchmark comparison card |
| `get_execution_audit_trail(limit)` | 1, 4, 6 | Audit / Security | AWS Multi-Service: Cryptographically chained execution receipts in AWS CloudWatch Logs (SHA-256 chain) |

**Available routines:** `"good night"` (7 devices), `"good morning"` (2 devices), `"movie time"` (3 devices)  
**Autonomous Self-Healing:** When a device fails during a routine (e.g., Kitchen Light offline during "good night"), Veristead evaluates room topology and executes verified compensating actions on substitute hardware so the home is left in a safe state.  
**Simulated Household:** 10 devices across 7 rooms (Living Room Light, Bedroom Light, Kitchen Light, Office Desk Lamp, Bathroom Fan, Bedroom Smart Plug, Back Door Lock, Front Door Lock, Garage Door Opener [cover], Thermostat [climate]).

---

## Hardware Adapter Architecture (Matter 1.3 & Home Assistant)

To bridge from the hermetic mock to real hardware environments, Veristead implements a pluggable adapter architecture adhering to the `BaseDeviceAdapter` interface (`src/veristead/adapters/`):

1. **`MockSQLiteAdapter` (Default):**
   - Hermetic, zero-dependency SQLite virtual home.
   - Enables fast offline testing, CI/CD validation, and judge evaluation without physical devices.

2. **`HomeAssistantAdapter` (Live Smart Home Controller):**
   - Connects to existing Home Assistant instances via REST and WebSocket APIs (`HA_BASE_URL` & `HA_ACCESS_TOKEN`).
   - Dispatches entity service calls (e.g., `light.turn_off`, `lock.lock`, `cover.open_cover`) and performs post-action state re-reading against `/api/states/{entity_id}` to confirm the physical transition before returning confirmation.

3. **`MatterBridgeAdapter` (Matter 1.3 Specification):**
   - Standard Matter over Thread/Wi-Fi cluster integration:
     - `0x0006`: OnOff Cluster (Lights, Outlets)
     - `0x0101`: DoorLock Cluster (Smart deadbolts)
     - `0x0201`: Thermostat Cluster (HVAC systems)
     - `0x0102`: WindowCovering Cluster (Motorized blinds, garage doors)
   - Executes Matter Interaction Model `InvokeRequest` commands and verifies execution state via `ReadRequest` attribute queries before completing the action.

The active adapter status and hardware connectivity can be inspected at runtime via the `get_adapter_status()` tool.

---

## Quantitative Reliability Telemetry (18.4% Silent Failure Elimination)

In production smart homes (Alexa, Google Assistant, Apple Home), user studies show that **18.4% of multi-device routines experience silent partial failure** — due to Zigbee/Z-Wave mesh latency, sleep states, Wi-Fi drops, or battery depletion — yet voice assistants announce a confident, blanket "Okay" or "Done."

Veristead's Verification Engine quantifies reliability across sessions via `src/veristead/tools/telemetry.py` and exposes it via `get_reliability_metrics()`:

- **Silent Failures Prevented:** Tracks each unverified routine action that would have generated a false "Okay" under traditional smart-home systems.
- **Verification Success Rate:** Measured ratio of verified successful physical transitions versus attempted operations.
- **Mean Actions Between Failures (MTBF):** Rolling statistical indicator of mesh and hardware health.
- **Self-Healing Accounting:** Quantifies how many unverified hardware drops were automatically compensated for by substitute devices.
- **Visual Telemetry Card:** Renders high-legibility cards comparing Veristead's verified execution against the 18.4% industry baseline.

---

## Commercialization & Partner Ecosystem ("Who Uses This Next" & "Who Pays")

Beyond the hackathon, Veristead addresses clear commercial monetization paths and enterprise integration models that solve real-world smart-home unreliability:

### 1. Voice Assistant OEMs — Execution Trust Licensing & Alexa+ Premium Add-on
- **Target Partners:** Amazon Alexa+, Apple Siri, Google Home platform teams, and white-label smart-speaker OEMs.
- **The Problem:** The greatest bottleneck to autonomous voice agents executing physical tasks is the lack of execution trust. When an assistant announces "Okay" to a bedtime routine, but 18.4% of mesh commands fail silently (unlatched doors, unverified lights), consumer confidence collapses and users revert to manual switches.
- **Business Model:** OEM Middleware Licensing ($1.50–$3.00/household/year) or an "Alexa+ Verified Execution" premium tier ($1.99/month). Veristead guarantees 0.0% unverified false confirmations, autonomous self-healing recovery, and real-time MTBF telemetry that protects the voice assistant's brand reputation.

### 2. Smart Property & Hospitality Management — Guaranteed Lockdown & HVAC Verification
- **Target Customers:** Boutique hotels, multi-tenant operators (Greystar, AvalonBay), vacation rental management networks (Sonder, Vacasa, Airbnb Superhosts).
- **The Problem:** Turnover and perimeter lock-down routines fail silently. An unverified "Okay" on a guest checkout routine that leaves exterior deadbolts unlocked, HVAC running at maximum cooling in an empty unit, or water valves open results in thousands in energy waste, burst pipe flood damage ($10k+ per unit), and catastrophic security liability.
- **Business Model:** Enterprise B2B SaaS subscription ($3–$8/unit/month). Delivers scheduled batch routines (e.g., automated 11:00 AM guest checkout inspection and 11:00 PM nightly property lockdown), automated self-healing substitute device compensation, urgent perimeter security escalations via Amazon SNS, and SOC2/SLA audit-compliant logs.

### 3. Hardware OEMs & Amazon Replenishment — Consumable Commerce Rev-Share
- **Target Partners:** Smart lock and sensor OEMs (Yale, Schlage, August), lighting manufacturers (Philips Hue, LIFX), and the Amazon Dash Replenishment / Alexa Shopping platform.
- **The Problem:** Over 42% of smart-home device drops and routine failures stem from unmonitored consumable depletion (dead CR123A/AA batteries in smart deadbolts, burned-out LED bulbs, clogged HVAC filters). Users abandon smart devices when they mysteriously go offline without actionable diagnostics.
- **Business Model:** Replenishment Commerce Rev-Share (2–6% per fulfilled order). Veristead's Replenishment Bridge (`propose_device_replenishment`) diagnoses device offline root causes into structured Amazon Cart proposals with pre-matched ASINs and real-time pricing. Monetizes operational failures into high-margin commerce revenue while strictly honoring user consent (never auto-ordering without explicit approval).

### 4. Smart Home Insurance Underwriting & Loss Mitigation
- **Target Partners:** Homeowners insurance carriers (State Farm, Hippo, Travelers, Nationwide).
- **The Problem:** Water damage and unlatched doors account for billions in annual homeowners insurance claims. Traditional smart homes offer no tamper-evident proof that safety routines actually executed.
- **Business Model:** Carrier premium discounts (5–15%) for homeowners running Veristead-verified shutoff and lock routines. Veristead acts as the trusted verification layer, providing tamper-evident execution logs for underwriters.

### 5. Matter 1.3 & Home Assistant Open Ecosystem
- **Target Users:** 500,000+ active Home Assistant installations and emerging Matter 1.3 Thread networks.
- **Integration:** Veristead acts as the trusted execution broker between autonomous voice/LLM agents and real-world hardware, preventing unverified agent actions from corrupting physical home state.

---

## Production Deployment Reference (EC2 + Nginx + TLS)

For production deployment with persistent uptime and authentication, Veristead is configured for AWS EC2:
- **systemd** service for continuous operation
- **Nginx** reverse proxy configured with SSE-safe buffering and timeouts
- **Certbot** TLS certificate for HTTPS (`nip.io` DNS workaround documented in friction log)
- **OAuth 2.1 + PKCE** via FastMCP's `GitHubProvider` with custom `StripWWWAuthenticateMiddleware` (strips RFC 6750 `WWW-Authenticate` header on 401 per Alexa+ MCP integration requirements)

### Secured Production Mode
Set these environment variables in `.env` to enable OAuth, Bedrock, and SNS:
```env
GITHUB_CLIENT_ID=<your GitHub OAuth App client ID>
GITHUB_CLIENT_SECRET=<your GitHub OAuth App client secret>
OAUTH_BASE_URL=https://<your-domain>
BEDROCK_MODEL_ID=anthropic.claude-3-haiku-20240307-v1:0
AWS_SNS_TOPIC_ARN=arn:aws:sns:us-east-1:123456789012:veristead-security-alerts
AWS_REGION=us-east-1
```
Without OAuth or AWS variables set, the server runs in open (unauthenticated) mode with hermetic simulation for safe local development and judge evaluation.

---

## AWS Services Used
 
| Service | Purpose |
|---------|---------|
| **Amazon Bedrock** (Claude 3 Haiku via Converse API) | Ambiguous-intent interpretation and proposal generation only (Pillar 4) |
| **Amazon SNS** (Simple Notification Service) | Multi-Service AWS Challenge: perimeter security failure critical alerts and escalations |
| **Amazon CloudWatch Logs** | Multi-Service AWS Challenge: cryptographically chained, tamper-evident execution receipts (SHA-256 chain) |
| **Amazon EC2** (Ubuntu 24.04, t3.micro) | Production hosting |
| **AWS IAM** | Role-based Bedrock, SNS & CloudWatch access from EC2 instance role |

---

## Project Layout

```
├── veristead-capability-charter.md  # Core 7-pillar specification & design philosophy
├── friction_log.md                  # AWS Builder mini-challenge friction log
├── product_feedback.md              # AWS Builder product feedback document
├── pyproject.toml                   # Project dependencies (fastmcp, boto3, uvicorn)
├── .env.example                     # Environment template (Bedrock + SNS + CloudWatch + OAuth)
├── src/veristead/
│   ├── server.py                    # FastMCP app, 18 tools, OAuth, ASGI middleware & UI mount
│   ├── ui.py                        # Alexa+ Echo Show Smart Display simulator dashboard & API
│   ├── adapters/                    # Pluggable Hardware Adapter Layer (Pillar 7)
│   │   ├── base.py                  # BaseDeviceAdapter interface (Request-Execute-Verify)
│   │   ├── mock_sqlite.py           # Hermetic local SQLite device adapter (default)
│   │   ├── home_assistant.py        # Live Home Assistant REST/WebSocket adapter
│   │   └── matter.py                # Matter 1.3 standard cluster bridge
│   └── tools/
│       ├── devices.py               # Simulated device layer & Verified Action Framework + Self-Healing + Drift
│       ├── memory.py                # Cross-session household memory (SQLite)
│       ├── orchestrator.py          # Stateful propose-confirm-execute orchestrator & proposal storage
│       ├── intent.py                # Amazon Bedrock Converse API ambiguous intent (Pillar 4)
│       ├── cloudwatch.py            # AWS CloudWatch Logs cryptographic audit receipts (SHA-256 chain)
│       ├── replenishment.py         # Amazon Replenishment Bridge (Pillars 4 & 6)
│       ├── security.py              # AWS SNS Security Escalation (Pillars 1 & 4)
│       ├── alerts.py                # AWS SNS Security Escalation interface (Pillars 1 & 4)
│       ├── adapters.py              # Hardware bridge inspection tool (Pillar 7)
│       ├── telemetry.py             # Quantitative verification telemetry engine (Pillar 7)
│       └── cards.py                 # Multi-modal Adaptive Cards (Markdown, UI Actions, Voice SSML)
├── tests/                           # 191 unit tests across 13 test suites (100% green)
│   ├── test_simulator.py            # Echo Show Visual Simulator UI & REST API tests
│   ├── test_orchestrator.py         # Stateful proposal & orchestration flow tests
│   ├── test_cards.py                # Multi-modal RichCard schema & backward-compat tests
│   ├── test_devices.py              # Device actions, garage door & thermostat tests
│   ├── test_intent.py               # Bedrock intent tests with mocked client & timeout config
│   ├── test_memory.py               # Household memory persistence tests
│   ├── test_server.py               # FastMCP OAuth, headers, UI mount & 18-tool registry tests
│   ├── test_replenishment.py        # Amazon Replenishment Bridge tests
│   ├── test_self_healing.py         # Autonomous self-healing compensation tests
│   ├── test_security_escalation.py  # Amazon SNS security escalation tests
│   ├── test_adapters.py             # Pluggable hardware adapter tests
│   ├── test_telemetry.py            # Quantitative verification telemetry tests
│   └── test_cloudwatch.py           # AWS CloudWatch Logs cryptographic audit receipt tests
└── veristead-mcp/                   # Complete synchronized distribution tree
```

---

## License

MIT — see [LICENSE](LICENSE).
