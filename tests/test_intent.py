import json

from veristead.tools import devices, intent


class _FakeBedrockClient:
    def __init__(self, response_text=None, raise_exc=None):
        self._response_text = response_text
        self._raise_exc = raise_exc
        self.last_call_kwargs = None

    def converse(self, **kwargs):
        self.last_call_kwargs = kwargs
        if self._raise_exc:
            raise self._raise_exc
        return {"output": {"message": {"content": [{"text": self._response_text}]}}}


def _seed(tmp_path, monkeypatch):
    monkeypatch.setattr(devices, "DB_PATH", tmp_path / "devices.db")


def test_missing_model_id_returns_error_without_calling_bedrock(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False)

    result = intent.interpret_command_impl("I'm cold")

    assert result["status"] == "error"
    assert "BEDROCK_MODEL_ID" in result["reason"]


def test_happy_path_returns_proposal_without_executing(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    monkeypatch.setenv("BEDROCK_MODEL_ID", "test-model-id")

    fake_response = json.dumps(
        {
            "device": "Thermostat",
            "action": "set:23",
            "message": "The room is 20C -- increase the thermostat to 23C?",
        }
    )
    client = _FakeBedrockClient(response_text=fake_response)

    result = intent.interpret_command_impl("I'm cold", client=client)

    assert result["status"] == "proposed"
    assert result["device"] == "Thermostat"
    assert result["action"] == "set:23"
    assert "23" in result["message"]

    # Confirm this tool never mutates anything itself.
    status_after = devices.get_device_status_impl("Thermostat")
    assert status_after[0]["state"]["temperature"] == 21


def test_bedrock_reports_its_own_interpretation_error(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    monkeypatch.setenv("BEDROCK_MODEL_ID", "test-model-id")

    fake_response = json.dumps({"error": "command does not map to any known device"})
    client = _FakeBedrockClient(response_text=fake_response)

    result = intent.interpret_command_impl("do something vague", client=client)

    assert result["status"] == "error"
    assert "does not map" in result["reason"]


def test_malformed_response_is_handled_gracefully(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    monkeypatch.setenv("BEDROCK_MODEL_ID", "test-model-id")

    client = _FakeBedrockClient(response_text="not valid json at all")

    result = intent.interpret_command_impl("I'm cold", client=client)

    assert result["status"] == "error"
    assert "parse" in result["reason"]


def test_bedrock_exception_is_caught_not_raised(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    monkeypatch.setenv("BEDROCK_MODEL_ID", "test-model-id")

    client = _FakeBedrockClient(raise_exc=RuntimeError("simulated network failure"))

    result = intent.interpret_command_impl("I'm cold", client=client)

    assert result["status"] == "error"
    assert "Bedrock call failed" in result["reason"]


def test_missing_device_or_action_field_is_an_error(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    monkeypatch.setenv("BEDROCK_MODEL_ID", "test-model-id")

    fake_response = json.dumps({"device": "Thermostat"})  # missing "action"
    client = _FakeBedrockClient(response_text=fake_response)

    result = intent.interpret_command_impl("I'm cold", client=client)

    assert result["status"] == "error"


def test_fenced_json_response_is_parsed(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    monkeypatch.setenv("BEDROCK_MODEL_ID", "test-model-id")

    inner = json.dumps(
        {
            "device": "Thermostat",
            "action": "set:23",
            "message": "Raise the thermostat to 23?",
        }
    )
    client = _FakeBedrockClient(response_text=f"```json\n{inner}\n```")

    result = intent.interpret_command_impl("I'm cold", client=client)

    assert result["status"] == "proposed"
    assert result["device"] == "Thermostat"
    assert result["action"] == "set:23"


def test_hallucinated_device_is_rejected(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    monkeypatch.setenv("BEDROCK_MODEL_ID", "test-model-id")

    fake_response = json.dumps(
        {
            "device": "Pool Heater",
            "action": "on",
            "message": "Turn on the pool heater?",
        }
    )
    client = _FakeBedrockClient(response_text=fake_response)

    result = intent.interpret_command_impl("warm the pool", client=client)

    assert result["status"] == "error"
    assert "not in the household inventory" in result["reason"]


def test_invalid_action_for_device_is_rejected(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    monkeypatch.setenv("BEDROCK_MODEL_ID", "test-model-id")

    fake_response = json.dumps(
        {
            "device": "Kitchen Light",
            "action": "lock",
            "message": "Lock the kitchen light?",
        }
    )
    client = _FakeBedrockClient(response_text=fake_response)

    result = intent.interpret_command_impl("secure the kitchen", client=client)

    assert result["status"] == "error"
    assert "not valid" in result["reason"]


def test_bedrock_client_timeout_and_retry_config(monkeypatch):
    """Bedrock client is configured with connect_timeout=3, read_timeout=5, retries=2."""
    monkeypatch.setattr(intent, "_bedrock_client", None)
    client = intent._get_bedrock_client()
    assert client.meta.config.connect_timeout == 3
    assert client.meta.config.read_timeout == 5
    assert client.meta.config.retries["total_max_attempts"] == 3  # max_attempts=2 + 1 initial


def test_markdown_fence_stripping_variations():
    """_strip_markdown_fences cleans 다양한 markdown code fences correctly."""
    raw1 = "```json\n{\"device\": \"Kitchen Light\", \"action\": \"on\"}\n```"
    assert json.loads(intent._strip_markdown_fences(raw1)) == {"device": "Kitchen Light", "action": "on"}

    raw2 = "```\n{\"device\": \"Kitchen Light\", \"action\": \"off\"}\n```"
    assert json.loads(intent._strip_markdown_fences(raw2)) == {"device": "Kitchen Light", "action": "off"}

    raw3 = "  ```json   {\"device\": \"Kitchen Light\", \"action\": \"on\"}   ```  "
    assert json.loads(intent._strip_markdown_fences(raw3)) == {"device": "Kitchen Light", "action": "on"}


def test_empty_or_whitespace_device_is_rejected(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    monkeypatch.setenv("BEDROCK_MODEL_ID", "test-model-id")

    fake_response = json.dumps({"device": "", "action": "on"})
    client = _FakeBedrockClient(response_text=fake_response)

    result = intent.interpret_command_impl("turn on", client=client)
    assert result["status"] == "error"

