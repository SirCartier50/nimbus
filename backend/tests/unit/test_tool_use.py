from unittest.mock import MagicMock, patch

from utils import tool_use


def _converse_response(stop_reason, content):
    return {"stopReason": stop_reason, "output": {"message": {"role": "assistant", "content": content}}}


def test_end_turn_returns_text_immediately():
    client = MagicMock()
    client.converse.return_value = _converse_response("end_turn", [{"text": "done"}])

    with patch("utils.llm.bedrock.get_bedrock_client", return_value=client):
        result = tool_use.run_tool_loop("sys", [{"role": "user", "content": [{"text": "hi"}]}], {"tools": []}, {})

    assert result["text"] == "done"
    assert client.converse.call_count == 1


def test_tool_use_invokes_handler_and_continues_loop():
    client = MagicMock()
    client.converse.side_effect = [
        _converse_response(
            "tool_use",
            [{"toolUse": {"toolUseId": "t1", "name": "my_tool", "input": {"x": 1}}}],
        ),
        _converse_response("end_turn", [{"text": "final answer"}]),
    ]
    handler = MagicMock(return_value={"ok": True})

    with patch("utils.llm.bedrock.get_bedrock_client", return_value=client):
        result = tool_use.run_tool_loop(
            "sys", [{"role": "user", "content": [{"text": "hi"}]}], {"tools": []}, {"my_tool": handler}
        )

    handler.assert_called_once_with({"x": 1})
    assert result["text"] == "final answer"
    assert client.converse.call_count == 2


def test_unknown_tool_name_reports_error_without_crashing():
    client = MagicMock()
    client.converse.side_effect = [
        _converse_response("tool_use", [{"toolUse": {"toolUseId": "t1", "name": "ghost_tool", "input": {}}}]),
        _converse_response("end_turn", [{"text": "ok"}]),
    ]
    with patch("utils.llm.bedrock.get_bedrock_client", return_value=client):
        result = tool_use.run_tool_loop("sys", [{"role": "user", "content": []}], {"tools": []}, {})

    # messages[2] is the tool-result turn sent back after the first tool_use response
    tool_result = result["messages"][2]["content"][0]["toolResult"]
    assert tool_result["status"] == "error"
    assert "Unknown tool" in tool_result["content"][0]["json"]["error"]
    assert result["text"] == "ok"


def test_handler_exception_is_caught_and_reported_as_tool_error():
    client = MagicMock()
    client.converse.side_effect = [
        _converse_response("tool_use", [{"toolUse": {"toolUseId": "t1", "name": "boom", "input": {}}}]),
        _converse_response("end_turn", [{"text": "recovered"}]),
    ]

    def handler(_params):
        raise ValueError("kaboom")

    with patch("utils.llm.bedrock.get_bedrock_client", return_value=client):
        result = tool_use.run_tool_loop("sys", [{"role": "user", "content": []}], {"tools": []}, {"boom": handler})

    tool_result = result["messages"][2]["content"][0]["toolResult"]
    assert tool_result["status"] == "error"
    assert "kaboom" in tool_result["content"][0]["json"]["error"]
    assert result["text"] == "recovered"


def test_max_tokens_stop_reason_ends_turn_without_malformed_retry():
    """Regression test: previously any stop reason other than end_turn/tool_use
    fell through silently and the loop re-called converse() with an invalid
    message list (last message already assistant, no new user turn)."""
    client = MagicMock()
    client.converse.return_value = _converse_response("max_tokens", [{"text": "partial answer..."}])

    with patch("utils.llm.bedrock.get_bedrock_client", return_value=client):
        result = tool_use.run_tool_loop("sys", [{"role": "user", "content": [{"text": "hi"}]}], {"tools": []}, {})

    assert client.converse.call_count == 1, "must not retry on a terminal non-tool_use stop reason"
    assert "partial answer" in result["text"]
    assert "max token limit" in result["text"]


def test_all_models_fail_returns_error_text_instead_of_raising():
    client = MagicMock()
    client.converse.side_effect = Exception("ThrottlingException")

    with patch("utils.llm.bedrock.get_bedrock_client", return_value=client):
        result = tool_use.run_tool_loop("sys", [{"role": "user", "content": [{"text": "hi"}]}], {"tools": []}, {})

    assert "All models failed" in result["text"]


def test_max_iterations_reached_returns_gracefully():
    client = MagicMock()
    client.converse.return_value = _converse_response(
        "tool_use", [{"toolUse": {"toolUseId": "t1", "name": "loop_tool", "input": {}}}]
    )
    handler = MagicMock(return_value={"keep": "going"})

    with patch("utils.llm.bedrock.get_bedrock_client", return_value=client):
        result = tool_use.run_tool_loop(
            "sys", [{"role": "user", "content": []}], {"tools": []}, {"loop_tool": handler}, max_iterations=3
        )

    assert client.converse.call_count == 3
    assert "maximum number of steps" in result["text"]
