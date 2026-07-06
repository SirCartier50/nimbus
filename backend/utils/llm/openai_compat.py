"""Groq and OpenRouter providers.

Both expose an OpenAI-compatible chat-completions API with tool calling, so a single
adapter covers them — only base_url, key, and model id differ. This translates the
canonical Bedrock Converse format into OpenAI's schema on the way in and back on the
way out, so the rest of Nimbus stays Bedrock-shaped and provider-unaware.

NOTE: every Nimbus agent depends on tool/function calling, so only tool-capable models
work here. Groq (e.g. llama-3.3-70b-versatile) and many OpenRouter models support it;
pick accordingly. HuggingFace is intentionally not implemented for this reason — see
PIPELINE_PLAN.md §5.

The pure translation helpers below take no OpenAI SDK objects on input (only on output
parsing), so they're unit-testable without the `openai` package installed.
"""
import json
import logging

logger = logging.getLogger("llm.openai_compat")


class OpenAICompatProvider:
    def __init__(self, base_url: str, api_key: str, model: str, extra_headers: dict = None):
        from openai import OpenAI  # local import: dep only needed when this provider is used

        self._model = model
        self._client = OpenAI(base_url=base_url, api_key=api_key, default_headers=extra_headers or {})

    def infer(self, system_prompt: str, messages: list, tool_config: dict = None) -> dict:
        oai_messages = [{"role": "system", "content": system_prompt}] + to_openai_messages(messages)
        kwargs = {
            "model": self._model,
            "messages": oai_messages,
            "max_tokens": 4096,
            "temperature": 0.1,
        }
        tools = to_openai_tools(tool_config or {})
        if tools:
            kwargs["tools"] = tools
        completion = self._client.chat.completions.create(**kwargs)
        return from_openai_response(completion)


# ---------------------------------------------------------------------------
# Pure translation helpers (canonical Bedrock format <-> OpenAI format)
# ---------------------------------------------------------------------------


def to_openai_tools(tool_config: dict) -> list:
    tools = []
    for t in tool_config.get("tools", []):
        spec = t["toolSpec"]
        tools.append({
            "type": "function",
            "function": {
                "name": spec["name"],
                "description": spec.get("description", ""),
                "parameters": spec["inputSchema"]["json"],
            },
        })
    return tools


def to_openai_messages(messages: list) -> list:
    out = []
    for msg in messages:
        role = msg["role"]
        content = msg.get("content", [])
        text_parts = [b["text"] for b in content if "text" in b]
        tool_uses = [b["toolUse"] for b in content if "toolUse" in b]
        tool_results = [b["toolResult"] for b in content if "toolResult" in b]

        # Bedrock packs tool results into a single user message; OpenAI wants one
        # 'tool' role message per result, keyed by the original tool-call id.
        if tool_results:
            for tr in tool_results:
                out.append({
                    "role": "tool",
                    "tool_call_id": tr["toolUseId"],
                    "content": _stringify(tr.get("content", [])),
                })
            if text_parts:
                out.append({"role": "user", "content": "\n".join(text_parts)})
            continue

        if role == "assistant" and tool_uses:
            out.append({
                "role": "assistant",
                "content": "\n".join(text_parts) or None,
                "tool_calls": [
                    {
                        "id": tu["toolUseId"],
                        "type": "function",
                        "function": {"name": tu["name"], "arguments": json.dumps(tu.get("input", {}))},
                    }
                    for tu in tool_uses
                ],
            })
            continue

        out.append({"role": role, "content": "\n".join(text_parts)})
    return out


def _stringify(content_blocks: list) -> str:
    parts = []
    for b in content_blocks:
        if "json" in b:
            parts.append(json.dumps(b["json"]))
        elif "text" in b:
            parts.append(b["text"])
    return "\n".join(parts)


def from_openai_response(completion) -> dict:
    """Translate an OpenAI chat-completion back into canonical {stop_reason, message}."""
    choice = completion.choices[0]
    msg = choice.message

    if getattr(msg, "tool_calls", None):
        content = []
        if msg.content:
            content.append({"text": msg.content})
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            content.append({"toolUse": {"toolUseId": tc.id, "name": tc.function.name, "input": args}})
        return {"stop_reason": "tool_use", "message": {"role": "assistant", "content": content}}

    stop = "max_tokens" if choice.finish_reason == "length" else "end_turn"
    return {"stop_reason": stop, "message": {"role": "assistant", "content": [{"text": msg.content or ""}]}}
