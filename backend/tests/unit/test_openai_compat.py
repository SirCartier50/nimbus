"""Tests for the Bedrock<->OpenAI translation layer. These exercise the pure
translation helpers only, so they run without the `openai` SDK installed."""
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from utils import llm
from utils.llm import openai_compat as oc


def test_tools_translate_to_openai_function_schema():
    tool_config = {
        "tools": [
            {
                "toolSpec": {
                    "name": "create_vpc",
                    "description": "Make a VPC",
                    "inputSchema": {"json": {"type": "object", "properties": {"CidrBlock": {"type": "string"}}}},
                }
            }
        ]
    }
    tools = oc.to_openai_tools(tool_config)
    assert tools == [
        {
            "type": "function",
            "function": {
                "name": "create_vpc",
                "description": "Make a VPC",
                "parameters": {"type": "object", "properties": {"CidrBlock": {"type": "string"}}},
            },
        }
    ]


def test_empty_tool_config_yields_no_tools():
    assert oc.to_openai_tools({}) == []
    assert oc.to_openai_tools({"tools": []}) == []


def test_text_messages_translate_to_plain_content():
    messages = [{"role": "user", "content": [{"text": "hello"}]}]
    assert oc.to_openai_messages(messages) == [{"role": "user", "content": "hello"}]


def test_assistant_tool_use_becomes_openai_tool_calls():
    messages = [
        {
            "role": "assistant",
            "content": [
                {"text": "calling a tool"},
                {"toolUse": {"toolUseId": "abc", "name": "create_vpc", "input": {"CidrBlock": "10.0.0.0/16"}}},
            ],
        }
    ]
    out = oc.to_openai_messages(messages)
    assert len(out) == 1
    assert out[0]["role"] == "assistant"
    assert out[0]["content"] == "calling a tool"
    assert out[0]["tool_calls"][0]["id"] == "abc"
    assert out[0]["tool_calls"][0]["function"]["name"] == "create_vpc"
    assert json.loads(out[0]["tool_calls"][0]["function"]["arguments"]) == {"CidrBlock": "10.0.0.0/16"}


def test_tool_results_become_one_tool_message_each():
    messages = [
        {
            "role": "user",
            "content": [
                {"toolResult": {"toolUseId": "abc", "content": [{"json": {"ok": True}}], "status": "success"}},
                {"toolResult": {"toolUseId": "def", "content": [{"json": {"ok": False}}], "status": "error"}},
            ],
        }
    ]
    out = oc.to_openai_messages(messages)
    assert [m["role"] for m in out] == ["tool", "tool"]
    assert out[0]["tool_call_id"] == "abc"
    assert json.loads(out[0]["content"]) == {"ok": True}
    assert out[1]["tool_call_id"] == "def"


def test_response_with_text_maps_to_end_turn():
    completion = SimpleNamespace(
        choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content="all done", tool_calls=None))]
    )
    result = oc.from_openai_response(completion)
    assert result["stop_reason"] == "end_turn"
    assert result["message"] == {"role": "assistant", "content": [{"text": "all done"}]}


def test_response_with_tool_calls_maps_to_tool_use():
    tc = SimpleNamespace(
        id="call_1",
        function=SimpleNamespace(name="create_vpc", arguments='{"CidrBlock": "10.0.0.0/16"}'),
    )
    completion = SimpleNamespace(
        choices=[SimpleNamespace(finish_reason="tool_calls", message=SimpleNamespace(content=None, tool_calls=[tc]))]
    )
    result = oc.from_openai_response(completion)
    assert result["stop_reason"] == "tool_use"
    block = result["message"]["content"][0]["toolUse"]
    assert block == {"toolUseId": "call_1", "name": "create_vpc", "input": {"CidrBlock": "10.0.0.0/16"}}


def test_response_length_finish_maps_to_max_tokens():
    completion = SimpleNamespace(
        choices=[SimpleNamespace(finish_reason="length", message=SimpleNamespace(content="cut off", tool_calls=None))]
    )
    assert oc.from_openai_response(completion)["stop_reason"] == "max_tokens"


def test_malformed_tool_arguments_degrade_to_empty_input():
    tc = SimpleNamespace(id="c", function=SimpleNamespace(name="x", arguments="{not json"))
    completion = SimpleNamespace(
        choices=[SimpleNamespace(finish_reason="tool_calls", message=SimpleNamespace(content=None, tool_calls=[tc]))]
    )
    result = oc.from_openai_response(completion)
    assert result["message"]["content"][0]["toolUse"]["input"] == {}


# --- provider factory (Groq / OpenRouter / HuggingFace via OpenAI-compat) --------


def test_factory_huggingface_requires_token(monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGINGFACE_API_KEY", raising=False)
    with pytest.raises(ValueError, match="HF_TOKEN"):
        llm.get_provider("huggingface")


def test_factory_huggingface_builds_openai_compat_at_hf_router(monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "hf_xyz")
    monkeypatch.setenv("HF_MODEL", "Qwen/Qwen2.5-72B-Instruct")
    with patch("utils.llm.openai_compat.OpenAICompatProvider") as Provider:
        llm.get_provider("huggingface")
    kwargs = Provider.call_args.kwargs
    assert kwargs["base_url"] == "https://router.huggingface.co/v1"
    assert kwargs["api_key"] == "hf_xyz"
    assert kwargs["model"] == "Qwen/Qwen2.5-72B-Instruct"


def test_factory_unknown_provider_rejected():
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        llm.get_provider("gpt5")
