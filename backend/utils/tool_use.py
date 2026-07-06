"""Backwards-compatible shim.

The tool-use loop now lives in utils/llm/ behind a provider abstraction (DEV-2).
This module re-exports the Bedrock-default entrypoints so existing imports
(`from utils.tool_use import run_tool_loop, NOVA_MODEL_ID`) keep working. New code
should import from utils.llm directly.
"""
from utils.llm import FALLBACK_MODEL_IDS, NOVA_MODEL_ID, get_provider, run_tool_loop

__all__ = ["run_tool_loop", "get_provider", "NOVA_MODEL_ID", "FALLBACK_MODEL_IDS"]
