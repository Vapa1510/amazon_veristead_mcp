# Veristead — verified smart-home execution for Alexa+

A self-hosted MCP server built for Amazon's **Build, Ship, Shape** hackathon
(Alexa+ track + AWS Builder mini-challenge).

**The problem:** Alexa+ already controls smart homes — that's not a gap.
What real users report is that the control is unreliable: routines fail
silently, wrong devices respond, and a confident "Okay" doesn't always mean
the light actually turned off. Veristead doesn't add a missing feature to
Alexa+; it makes an existing one trustworthy.

**The rule everything else follows from:** never claim a physical action
succeeded without checking that it did.

## Status

**Phase 0/1 scaffold.** The MCP server
runs locally over Streamable HTTP with all 8 tools working end to end
against a mocked household. Not yet included (coming in later phases):

- [ ] OAuth 2.1 + PKCE account linking for Alexa+
- [ ] Amazon Bedrock layer for ambiguous-intent interpretation (e.g. "I'm cold")
- [ ] Deployment + `alexa-ai` add-on scaffolding/deploy
- [ ] MCP Apps / card responses for visual surfaces

See `veristead-capability-charter.md` for the full six-pillar spec.

## Tools

| Tool | Description |
|---|---|
| `get_device_status(name_or_room)` | Read-only status for matching devices. |
| `get_room_devices(room)` | List every device in a room. |
| `execute_device_action(device, action)` | Runs an action and re-verifies device state before confirming — never a blind "Okay." |
| `run_routine(routine_name)` | Runs a named multi-device routine (`"good night"`, `"good morning"`) and reports a consolidated result, including any devices that failed or were offline. |
| `simulate_offline_device(device, offline)` | Demo tool — deliberately takes a device offline to trigger the partial-failure scenario on command. |
| `recall_context(topic, limit)` | Recalls recent household context, optionally filtered to a topic. |
| `view_memory()` | Full transparency dump of everything remembered about the household. |
| `forget_topic(topic)` | Deletes all memory entries under a topic. |

## Quick start

```bash
git clone <your-repo-url>
cd veristead-mcp
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env

python -m veristead.server
```

The server starts on `http://0.0.0.0:8000/mcp/` (Streamable HTTP, MCP spec
2025-11-25+). Point any MCP client or the MCP Inspector at that URL.

**Try the flagship demo moment:**
```
1. Call simulate_offline_device("Kitchen Light", true)
2. Call run_routine("good night")
3. Observe: "4 succeeded, 1 failed (Kitchen Light)" — not a blanket "done"
```

Run tests:

```bash
python -m pytest tests/ -v
```

## Project layout

```
src/veristead/
  server.py        # FastMCP app, tool registration, entry point
  tools/
    devices.py      # mocked smart-home layer, Verified Action Framework
    memory.py        # cross-session household memory, SQLite-backed
tests/              # unit tests (hermetic SQLite, no network)
data/                # local devices.db + memory.db (gitignored)
```

## License

MIT — see [LICENSE](LICENSE).
