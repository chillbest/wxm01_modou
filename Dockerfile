FROM python:3.13.18-slim
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev
COPY src ./src
COPY config.toml ./config.toml
ENV PYTHONPATH=/app/src MODOU_WEB_DATA=/app/data/web MODOU_BANGUMI_DUMP=/app/data/bangumi_locale
EXPOSE 4001
CMD ["/app/.venv/bin/python", "-m", "modou.web"]
