# Stage 1: Install dependencies into a venv (NOT `pip install --user`, which lands
# packages under /root/.local — unreachable by the non-root runtime user below since
# /root isn't traversable by other users. A venv at a plain path avoids that entirely.)
FROM python:3.11-slim AS builder

WORKDIR /app

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install from the pinned lock (generated on Linux via `pip-compile`, see
# requirements.lock.txt header) so two builds of the same commit produce the
# same image. requirements.txt stays the human-edited range file.
COPY requirements.lock.txt .
RUN pip install --no-cache-dir -r requirements.lock.txt

# Stage 2: Runtime — only the venv copied over, no pip or build tools
FROM python:3.11-slim

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH"

RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app /opt/venv

COPY --chown=appuser:appuser . .

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=2)"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
