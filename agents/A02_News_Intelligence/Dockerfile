FROM python:3.11-slim AS base

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    "pydantic>=2.7,<3" \
    "pydantic-settings>=2.3,<3" \
    "aiosqlite>=0.20"

COPY . .

ENV PYTHONPATH=/app
ENV APP_ENV=production

RUN python -c "from agents.A02_News_Intelligence.config.paths import ensure_data_directories; ensure_data_directories()"

HEALTHCHECK --interval=60s --timeout=10s --retries=3 \
    CMD python -m agents.A02_News_Intelligence.cli doctor || exit 1

ENTRYPOINT ["python", "-m", "agents.A02_News_Intelligence.cli"]
CMD ["doctor"]
