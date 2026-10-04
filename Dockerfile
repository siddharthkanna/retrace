# One image for every Python service; docker-compose.yml picks which one to run.
FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /bin/uv
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH"
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen
COPY services ./services
COPY scenarios ./scenarios
COPY tests ./tests
