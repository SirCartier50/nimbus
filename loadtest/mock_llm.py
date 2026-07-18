"""Mock OpenAI-compatible LLM for load testing.

Serves /v1/chat/completions with a canned, tool-free reply after a configurable
artificial latency (MOCK_LATENCY_MS, default 300). This lets k6 drive REAL chat
turns through the full pipeline (auth → rate limit → LangGraph → Postgres
persistence → SSE) without paying a model provider or tripping their rate limits.
The latency knob is what makes capacity tests honest: turn concurrency =
arrival rate × turn duration, so a slow mock simulates a thinking model.
"""
import asyncio
import os
import time

from fastapi import FastAPI

app = FastAPI()

LATENCY_MS = int(os.getenv("MOCK_LATENCY_MS", "300"))

_REPLY = (
    "Amazon S3 is object storage: you create buckets and store files in them. "
    "This is a canned load-test reply — no model was consulted."
)


@app.post("/v1/chat/completions")
async def chat_completions(body: dict):
    await asyncio.sleep(LATENCY_MS / 1000)
    return {
        "id": "chatcmpl-mock",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": body.get("model", "mock"),
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": _REPLY},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 30, "total_tokens": 40},
    }


@app.get("/health")
async def health():
    return {"ok": True}
