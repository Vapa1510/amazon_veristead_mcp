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
