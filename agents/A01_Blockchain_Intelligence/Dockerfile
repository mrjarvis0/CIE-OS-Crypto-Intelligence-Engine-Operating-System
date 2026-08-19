FROM python:3.11-slim AS base

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir ".[all]"

COPY . .

ENV PYTHONPATH=/app
ENV A01_ENVIRONMENT=production

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "from config.constants import PROJECT_NAME; print(PROJECT_NAME)"

ENTRYPOINT ["python", "-m", "cli.main"]
CMD ["doctor"]
