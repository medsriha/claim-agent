FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_SYNC=1 \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app

ENV COVERAGE_FILE=/tmp/.coverage \
    PYTEST_ADDOPTS="-p no:cacheprovider"

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project

COPY README.md ./
COPY src/ src/
COPY tools/ tools/
COPY tests/ tests/
RUN uv sync --locked

RUN useradd --create-home --uid 10001 claims \
    && mkdir -p /data /cache \
    && chown claims:claims /data /cache
USER claims

EXPOSE 8000

CMD ["uvicorn", "claim_agent.app:app", "--host", "0.0.0.0", "--port", "8000"]
