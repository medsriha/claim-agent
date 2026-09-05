# The Python image. One image runs two things: the claims service, and the ShipBob
# stand-in the demonstration reads from. They share every dependency, so a second
# image would only be a second thing to build and wait for.
FROM python:3.11-slim

# Pinned so a rebuild months from now resolves the same dependencies this one did.
COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_SYNC=1 \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app

# The suite can be run in this image, and it measures coverage as it goes. The code is not
# the running user's to write to, so the tally and the cache go somewhere that is.
ENV COVERAGE_FILE=/tmp/.coverage \
    PYTEST_ADDOPTS="-p no:cacheprovider"

WORKDIR /app

# Dependencies first, on their own layer. Editing a source file then rebuilds in
# seconds instead of resolving and downloading everything again.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project

# The development group comes too, and deliberately. The stand-in serves the very same
# sample records the tests use, and reading them pulls in a test library — so an image
# without the development dependencies has a claims service but nothing for it to read.
# It also means the suite can be run in the container, against exactly what ships in it.
COPY README.md ./
COPY src/ src/
COPY tools/ tools/
COPY tests/ tests/
RUN uv sync --locked

# Nothing here needs to be root, so nothing here is. The two writable directories are
# made and handed over now, because an empty volume mounted over one of them takes the
# ownership it finds in the image.
RUN useradd --create-home --uid 10001 claims \
    && mkdir -p /data /cache \
    && chown claims:claims /data /cache
USER claims

EXPOSE 8000

CMD ["uvicorn", "claim_agent.app:app", "--host", "0.0.0.0", "--port", "8000"]
