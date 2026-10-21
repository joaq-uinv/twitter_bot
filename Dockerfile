# Docker Hub (2026-10-09, plan A-9) and then AWS ECR Public (2026-10-20, A-12) both
# rate-limited anonymous pulls from shared CI IPs. Same official image, served from
# Google's Docker Hub mirror.
FROM mirror.gcr.io/library/python:3.12-slim AS base
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv
WORKDIR /app

# Dependency layer, cached independently of source
COPY pyproject.toml ./
RUN uv pip install --system --no-cache '.[dev]' 2>/dev/null || \
    uv pip install --system --no-cache \
      httpx defusedxml pydantic pydantic-settings pytest pytest-cov hypothesis respx

COPY src/ ./src/
COPY tests/ ./tests/
ENV PYTHONPATH=/app/src

# Non-root; /data is the state volume mountpoint
RUN useradd -r -u 10001 -m relay && mkdir -p /data && chown -R relay:relay /data /app
USER relay

ENTRYPOINT ["python", "-m", "tweet_relay.cli"]
CMD ["run"]
