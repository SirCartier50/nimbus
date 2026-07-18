"""LLM provider abstraction (DEV-2).

get_provider() selects an adapter; run_tool_loop() is the drop-in convenience the
agents call. By default it uses the env-selected provider (LLM_PROVIDER), which is
Bedrock unless overridden, so existing call sites keep working unchanged. Pass an
explicit provider name (or instance) to run_tool_loop() to override per call —
that's the hook the pipeline uses to honor a user's chosen model.
"""
import os

from config import MODEL_DEFAULTS
from utils.llm.base import _text_of, run_loop
from utils.llm.bedrock import FALLBACK_MODEL_IDS, NOVA_MODEL_ID, BedrockProvider

__all__ = ["run_tool_loop", "run_completion", "get_provider", "NOVA_MODEL_ID", "FALLBACK_MODEL_IDS"]


def get_provider(name: str = None):
    # Default is OpenRouter, NOT Bedrock: the bedrock default silently routed
    # every provider-less call (Bodyguard patrols, unset LLM_PROVIDER) to Nova
    # on the operator's AWS bill. Bedrock remains constructible here for ops/
    # tests, but it is no longer user-selectable (not in chat.KNOWN_PROVIDERS).
    name = (name or os.getenv("LLM_PROVIDER", "openrouter")).lower()

    if name == "bedrock":
        return BedrockProvider()

    if name == "groq":
        from utils.llm.openai_compat import OpenAICompatProvider

        key = os.getenv("GROQ_API_KEY")
        if not key:
            raise ValueError("GROQ_API_KEY is not set")
        return OpenAICompatProvider(
            base_url="https://api.groq.com/openai/v1",
            api_key=key,
            model=os.getenv("GROQ_MODEL", MODEL_DEFAULTS["groq"]),
        )

    if name == "openrouter":
        from utils.llm.openai_compat import OpenAICompatProvider

        key = os.getenv("OPENROUTER_API_KEY")
        if not key:
            raise ValueError("OPENROUTER_API_KEY is not set")
        return OpenAICompatProvider(
            # Overridable so a load/integration harness can point this at a local
            # OpenAI-compatible mock instead of the real (paid) endpoint.
            base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
            api_key=key,
            model=os.getenv("OPENROUTER_MODEL", MODEL_DEFAULTS["openrouter"]),
        )

    if name in ("huggingface", "hf"):
        from utils.llm.openai_compat import OpenAICompatProvider

        key = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_API_KEY")
        if not key:
            raise ValueError("HF_TOKEN is not set")
        # HuggingFace Inference Providers expose an OpenAI-compatible router, so the same
        # adapter works. CRITICAL: every Nimbus agent uses tool calling — pick a model
        # that supports it (e.g. DeepSeek-V3, Qwen2.5-72B-Instruct, Llama-3.3-70B-Instruct);
        # many HF-served models do NOT, and the agents will silently fail without it.
        return OpenAICompatProvider(
            base_url="https://router.huggingface.co/v1",
            api_key=key,
            model=os.getenv("HF_MODEL", MODEL_DEFAULTS["huggingface"]),
        )

    raise ValueError(
        f"Unknown LLM provider '{name}'. Options: bedrock, groq, openrouter, huggingface."
    )


def run_tool_loop(system_prompt, messages, tool_config, tool_handlers, max_iterations=15, provider=None):
    prov = provider if hasattr(provider, "infer") else get_provider(provider)
    return run_loop(prov, system_prompt, messages, tool_config, tool_handlers, max_iterations)


def run_completion(system_prompt, user_message, provider=None) -> str:
    """Single tool-free model call returning plain text. Used by the Critic and
    Summary agents, which reason over text and don't need tools."""
    prov = provider if hasattr(provider, "infer") else get_provider(provider)
    messages = [{"role": "user", "content": [{"text": user_message}]}]
    response = prov.infer(system_prompt, messages, None)
    return _text_of(response["message"])
