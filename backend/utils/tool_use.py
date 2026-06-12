import json
import logging

from utils.aws_clients import get_bedrock_client

logger = logging.getLogger("tool_use")

NOVA_MODEL_ID = "us.amazon.nova-2-lite-v1:0"
FALLBACK_MODEL_IDS = [
    "amazon.nova-2-lite-v1:0",
    "us.amazon.nova-lite-v1:0",
    "amazon.nova-lite-v1:0",
    "us.amazon.nova-micro-v1:0",
    "amazon.nova-micro-v1:0",
]


def run_tool_loop(
    system_prompt: str,
    messages: list,
    tool_config: dict,
    tool_handlers: dict,
    max_iterations: int = 15,
) -> dict:
    """
    Shared Bedrock tool use loop.

    Sends messages to Bedrock with tool definitions. When the model requests
    a tool call, executes it via tool_handlers and sends the result back.
    Repeats until the model returns end_turn or max_iterations is hit.

    Returns: {"text": str, "messages": list}
    """
    client = get_bedrock_client()
    messages = list(messages)  # don't mutate caller's list

    model_ids = [NOVA_MODEL_ID] + FALLBACK_MODEL_IDS
    working_model = None

    for iteration in range(max_iterations):
        last_error = None

        # Try each model until one works
        models_to_try = [working_model] if working_model else model_ids
        response = None

        for model_id in models_to_try:
            try:
                response = client.converse(
                    modelId=model_id,
                    messages=messages,
                    system=[{"text": system_prompt}],
                    toolConfig=tool_config,
                    inferenceConfig={"maxTokens": 4096, "temperature": 0.1},
                )
                working_model = model_id
                break
            except Exception as e:
                last_error = str(e)
                logger.warning(f"Model {model_id} failed: {e}")
                continue

        if response is None:
            return {
                "text": f"All models failed. Last error: {last_error}",
                "messages": messages,
            }

        stop_reason = response.get("stopReason", "end_turn")
        output_message = response["output"]["message"]
        messages.append(output_message)

        # If the model is done talking, extract text and return
        if stop_reason == "end_turn":
            text_parts = [
                block["text"]
                for block in output_message["content"]
                if "text" in block
            ]
            return {
                "text": "\n".join(text_parts),
                "messages": messages,
            }

        # If the model wants to use tools, execute them
        if stop_reason == "tool_use":
            tool_results = []

            for block in output_message["content"]:
                if "toolUse" not in block:
                    continue

                tool_use = block["toolUse"]
                tool_name = tool_use["name"]
                tool_input = tool_use.get("input", {})
                tool_use_id = tool_use["toolUseId"]

                logger.info(f"Tool call: {tool_name}({json.dumps(tool_input)[:200]})")

                if tool_name in tool_handlers:
                    try:
                        result = tool_handlers[tool_name](tool_input)
                        tool_results.append({
                            "toolResult": {
                                "toolUseId": tool_use_id,
                                "content": [{"json": result}],
                                "status": "success",
                            }
                        })
                    except Exception as e:
                        logger.error(f"Tool {tool_name} failed: {e}")
                        tool_results.append({
                            "toolResult": {
                                "toolUseId": tool_use_id,
                                "content": [{"json": {"error": str(e)}}],
                                "status": "error",
                            }
                        })
                else:
                    tool_results.append({
                        "toolResult": {
                            "toolUseId": tool_use_id,
                            "content": [{"json": {"error": f"Unknown tool: {tool_name}"}}],
                            "status": "error",
                        }
                    })

            # Send tool results back to the model
            messages.append({"role": "user", "content": tool_results})

    # Hit max iterations
    return {
        "text": "I reached the maximum number of steps. Here is what I found so far.",
        "messages": messages,
    }
