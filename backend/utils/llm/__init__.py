"""LLM provider abstraction (DEV-2).

get_provider() selects an adapter; run_tool_loop() is the drop-in convenience the
agents call. By default it uses the env-selected provider (LLM_PROVIDER), which is
`openrouter` unless overridden (Bedrock was removed as the default on 2026-07-15 —
it silently billed the operator's AWS account; the class is kept for tests only).
Pass an explicit provider name (or instance) to run_tool_loop() to override per
call — that's the hook the pipeline uses to honor a user's chosen model. Default
model IDs live in config.MODEL_DEFAULTS (one edit per model drop), each overridable
via the matching <PROVIDER>_MODEL env var.
"""
import os

from config import MODEL_DEFAULTS
from utils.llm.base import _text_of, run_loop
from utils.llm.bedrock import FALLBACK_MODEL_IDS, NOVA_MODEL_ID, BedrockProvider

__all__ = ["run_tool_loop", "run_completion", "get_provider", "NOVA_MODEL_ID", "FALLBACK_MODEL_IDS"]


def get_provider(name: str = None, api_key: str = None, model: str = None):
    """`api_key`, when given, overrides the shared operator env var — this is how
    a user's own key (routes/chat.py's _resolve_provider, decrypted from
    UserSettings.provider_keys_enc) gets used for their turn instead of the
    server-wide credential. `model` similarly overrides the <PROVIDER>_MODEL env
    var / config.MODEL_DEFAULTS default (UserSettings.provider_models)."""
    # Default is OpenRouter, NOT Bedrock: the bedrock default silently routed
    # every provider-less call (Bodyguard patrols, unset LLM_PROVIDER) to Nova
    # on the operator's AWS bill. Bedrock remains constructible here for ops/
    # tests, but it is no longer user-selectable (not in config.KNOWN_PROVIDERS).
    name = (name or os.getenv("LLM_PROVIDER", "openrouter")).lower()

    if name == "bedrock":
        return BedrockProvider()

    if name == "groq":
        from utils.llm.openai_compat import OpenAICompatProvider

        key = api_key or os.getenv("GROQ_API_KEY")
        if not key:
            raise ValueError("GROQ_API_KEY is not set")
        return OpenAICompatProvider(
            base_url="https://api.groq.com/openai/v1",
            api_key=key,
            model=model or os.getenv("GROQ_MODEL", MODEL_DEFAULTS["groq"]),
        )

    if name == "openrouter":
        from utils.llm.openai_compat import OpenAICompatProvider

        key = api_key or os.getenv("OPENROUTER_API_KEY")
        if not key:
            raise ValueError("OPENROUTER_API_KEY is not set")
        return OpenAICompatProvider(
            # Overridable so a load/integration harness can point this at a local
            # OpenAI-compatible mock instead of the real (paid) endpoint.
            base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
            api_key=key,
            model=model or os.getenv("OPENROUTER_MODEL", MODEL_DEFAULTS["openrouter"]),
        )

    if name == "local":
        from utils.llm.openai_compat import OpenAICompatProvider

        # Dev-only escape hatch: point at any OpenAI-compatible server running on
        # the host machine (Ollama, LM Studio, vLLM, llama.cpp server) — same
        # OpenAICompatProvider, just a different base_url, so swapping back to a
        # real provider later is a one-line env change, not a code change.
        # host.docker.internal resolves to the host from inside the backend
        # container on Docker Desktop (Windows/Mac); on native Linux Docker you'd
        # need --add-host=host.docker.internal:host-gateway or a LAN IP instead.
        # Deliberately NOT in config.KNOWN_PROVIDERS — never user-selectable via
        # Settings > API Keys or the chat model switcher, only LLM_PROVIDER=local.
        return OpenAICompatProvider(
            base_url=os.getenv("LOCAL_LLM_BASE_URL", "http://host.docker.internal:11434/v1"),
            # Most local servers (Ollama included) don't check the key at all —
            # the OpenAI SDK just requires the field to be a non-empty string.
            api_key=api_key or os.getenv("LOCAL_LLM_API_KEY", "local-no-key-needed"),
            model=model or os.getenv("LOCAL_LLM_MODEL", "qwen2.5:14b"),
        )

    if name in ("huggingface", "hf"):
        from utils.llm.openai_compat import OpenAICompatProvider

        key = api_key or os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_API_KEY")
        if not key:
            raise ValueError("HF_TOKEN is not set")
        # HuggingFace Inference Providers expose an OpenAI-compatible router, so the same
        # adapter works. CRITICAL: every Nimbus agent uses tool calling — pick a model
        # that supports it (e.g. DeepSeek-V3, Qwen2.5-72B-Instruct, Llama-3.3-70B-Instruct);
        # many HF-served models do NOT, and the agents will silently fail without it.
        return OpenAICompatProvider(
            base_url="https://router.huggingface.co/v1",
            api_key=key,
            model=model or os.getenv("HF_MODEL", MODEL_DEFAULTS["huggingface"]),
        )

    raise ValueError(
        f"Unknown LLM provider '{name}'. Options: bedrock, groq, openrouter, huggingface, local."
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
