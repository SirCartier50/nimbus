"""Startup environment validation (PROD-2).

One aggregated, human-readable failure at boot instead of a cryptic traceback
minutes later on the first request that happens to touch the missing var. Call
`validate_environment()` after load_dotenv() and before the app starts serving.

This deliberately does NOT replace the `os.getenv(...)` call sites scattered
through the codebase — those defaults are fine and local to their feature. What
must be centralized is the *contract*: which vars are required for the process
to be viable at all, which are strongly recommended, and that every numeric
tunable actually parses. The full catalog of supported vars lives in
backend/.env.example.
"""
import logging
import os

logger = logging.getLogger("config")

# Default chat model per provider — the ONE place to bump when a better model
# drops, instead of hunting inline literals. Each is overridable at runtime via
# the matching <PROVIDER>_MODEL env var (see get_provider in utils/llm). Keep
# these to smart, tool-capable models (the product needs reliable tool calling —
# ~70B+ / equivalent); a model that can't call tools will silently fail here.
MODEL_DEFAULTS = {
    "openrouter": "meta-llama/llama-3.3-70b-instruct",
    "groq": "llama-3.3-70b-versatile",
    "huggingface": "deepseek-ai/DeepSeek-V3-0324",
}

# Vars without which the process cannot do its job at all.
_REQUIRED_COMMON = {
    "DATABASE_URL": "Postgres connection string (postgresql+asyncpg://...)",
    "AWS_ACCESS_KEY_ID": "Nimbus's own service identity — used only to call sts:AssumeRole into user accounts",
    "AWS_SECRET_ACCESS_KEY": "secret for AWS_ACCESS_KEY_ID",
}
_REQUIRED_BY_ROLE = {
    "api": {"CLERK_ISSUER": "Clerk JWT issuer URL — auth cannot verify a single request without it"},
    "worker": {},
}

# Missing these won't stop the process, but something user-visible degrades.
_RECOMMENDED = {
    "OPENROUTER_API_KEY": "the default LLM provider — chat turns will error until a provider key exists",
    "REDIS_URL": "shared rate limits/caches across workers — absent, each process keeps its own",
}

# Every numeric tunable: (env name, parser). A typo'd value should fail loudly
# at boot, not deep inside a request as ValueError('invalid literal for int()').
_NUMERIC = [
    ("DB_POOL_SIZE", int),
    ("DB_MAX_OVERFLOW", int),
    ("MAX_CONCURRENT_TURNS", int),
    ("TURN_TIMEOUT_SECONDS", float),
    ("SHUTDOWN_DRAIN_SECONDS", float),
    ("RATE_LIMIT_CHAT_PER_MINUTE", int),
    ("RATE_LIMIT_DEFAULT_PER_MINUTE", int),
]


def validate_environment(role: str = "api") -> None:
    """Raise RuntimeError listing EVERY problem at once when required config is
    missing/malformed; log warnings for recommended-but-absent vars."""
    problems = []

    required = {**_REQUIRED_COMMON, **_REQUIRED_BY_ROLE.get(role, {})}
    for name, why in required.items():
        if not os.getenv(name):
            problems.append(f"  - {name} is not set ({why})")

    for name, parse in _NUMERIC:
        raw = os.getenv(name)
        if raw is not None:
            try:
                parse(raw)
            except ValueError:
                problems.append(f"  - {name}={raw!r} is not a valid {parse.__name__}")

    if problems:
        raise RuntimeError(
            f"Refusing to start the {role} with invalid configuration:\n" + "\n".join(problems)
        )

    for name, why in _RECOMMENDED.items():
        if not os.getenv(name):
            logger.warning("%s is not set — %s", name, why)
