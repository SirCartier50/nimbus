"""Provider-agnostic tool-use loop.

The canonical message/tool format used throughout Nimbus is Amazon Bedrock's
Converse shape — messages are {role, content: [{text} | {toolUse} | {toolResult}]},
tools are {toolSpec: {name, description, inputSchema: {json}}}. Every agent and the
chat route already speak this format, so it's the internal lingua franca: non-Bedrock
providers translate to/from it inside their own adapter, and the loop below never has
to know which provider it's driving.

A provider implements one method — infer() — which performs a single model call and
returns a canonical-shaped {stop_reason, message}. This module owns the loop itself:
dispatch tool calls, feed results back, and stop on end_turn / a terminal stop reason
/ max_iterations.
"""
import json
import logging
from typing import Protocol

logger = logging.getLogger("llm")

_STOP_NOTES = {
    "max_tokens": "(response was cut off — it hit the max token limit)",
    "content_filtered": "(response was blocked by content filtering)",
    "guardrail_intervened": "(response was blocked by a guardrail)",
    "stop_sequence": "(response stopped at a stop sequence)",
}


class LLMProvider(Protocol):
    def infer(self, system_prompt: str, messages: list, tool_config: dict) -> dict:
        """One model call. Returns {"stop_reason": str, "message": {role, content: [...]}}
        in canonical (Bedrock Converse) shape. Raises on an unrecoverable provider error."""
        ...


def run_loop(provider, system_prompt, messages, tool_config, tool_handlers, max_iterations=15) -> dict:
    """Drive `provider` through a tool-use conversation until it stops. Returns
    {"text": str, "messages": list} — messages in canonical format, ready to persist."""
    messages = list(messages)  # don't mutate the caller's list

    for _ in range(max_iterations):
        try:
            response = provider.infer(system_prompt, messages, tool_config)
        except Exception as e:
            logger.warning(f"Provider inference failed: {e}")
            return {"text": f"All models failed. Last error: {e}", "messages": messages}

        stop_reason = response.get("stop_reason", "end_turn")
        output_message = response["message"]
        messages.append(output_message)

        if stop_reason == "end_turn":
            return {"text": _text_of(output_message), "messages": messages}

        # Any non-tool_use terminal stop (max_tokens, content_filtered, ...) ends the
        # turn without a tool_use block. Looping again would re-infer on a message list
        # whose last turn is already the assistant's — return what text we have instead.
        if stop_reason != "tool_use":
            note = _STOP_NOTES.get(stop_reason, f"(stopped early: {stop_reason})")
            logger.warning(f"Unhandled stop reason '{stop_reason}' — ending turn early")
            return {"text": (_text_of(output_message) + f"\n\n{note}").strip(), "messages": messages}

        tool_results = [
            _run_one_tool(block["toolUse"], tool_handlers)
            for block in output_message["content"]
            if "toolUse" in block
        ]
        messages.append({"role": "user", "content": tool_results})

    return {"text": "I reached the maximum number of steps. Here is what I found so far.", "messages": messages}


def _text_of(message: dict) -> str:
    return "\n".join(b["text"] for b in message.get("content", []) if "text" in b)


def _run_one_tool(tool_use: dict, tool_handlers: dict) -> dict:
    name = tool_use["name"]
    tool_input = tool_use.get("input", {})
    tool_use_id = tool_use["toolUseId"]
    logger.info(f"Tool call: {name}({json.dumps(tool_input)[:200]})")

    if name in tool_handlers:
        try:
            payload, status = tool_handlers[name](tool_input), "success"
        except Exception as e:
            logger.error(f"Tool {name} failed: {e}")
            payload, status = {"error": str(e)}, "error"
    else:
        payload, status = {"error": f"Unknown tool: {name}"}, "error"

    return {"toolResult": {"toolUseId": tool_use_id, "content": [{"json": payload}], "status": status}}
