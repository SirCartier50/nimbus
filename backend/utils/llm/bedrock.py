"""Amazon Bedrock provider — the default. Speaks the canonical format natively,
so infer() is a thin wrapper over converse() with Nova model fallback.

The fallback list exists because the exact Nova model id that's callable varies by
region and account entitlement; we try them in order and cache the first that works
for the rest of this loop (a fresh provider is built per run_tool_loop call, so the
cache never leaks across requests)."""
import logging

from utils.aws_clients import get_bedrock_client

logger = logging.getLogger("llm.bedrock")

NOVA_MODEL_ID = "us.amazon.nova-2-lite-v1:0"
FALLBACK_MODEL_IDS = [
    "amazon.nova-2-lite-v1:0",
    "us.amazon.nova-lite-v1:0",
    "amazon.nova-lite-v1:0",
    "us.amazon.nova-micro-v1:0",
    "amazon.nova-micro-v1:0",
]


class BedrockProvider:
    def __init__(self, model_id: str = None):
        # An explicit model_id pins to one model; otherwise try the Nova list in order.
        self._model_ids = [model_id] if model_id else [NOVA_MODEL_ID] + FALLBACK_MODEL_IDS
        self._working_model = None
        self._client = None

    def infer(self, system_prompt: str, messages: list, tool_config: dict = None) -> dict:
        if self._client is None:
            self._client = get_bedrock_client()

        models_to_try = [self._working_model] if self._working_model else self._model_ids
        last_error = None
        for model_id in models_to_try:
            try:
                kwargs = dict(
                    modelId=model_id,
                    messages=messages,
                    system=[{"text": system_prompt}],
                    inferenceConfig={"maxTokens": 4096, "temperature": 0.1},
                )
                # Omit toolConfig entirely for tool-free calls (critic/summary) —
                # Bedrock rejects an empty tools list.
                if tool_config and tool_config.get("tools"):
                    kwargs["toolConfig"] = tool_config
                response = self._client.converse(**kwargs)
                self._working_model = model_id
                return {
                    "stop_reason": response.get("stopReason", "end_turn"),
                    "message": response["output"]["message"],
                }
            except Exception as e:
                last_error = e
                logger.warning(f"Model {model_id} failed: {e}")
                continue
        raise RuntimeError(last_error)
