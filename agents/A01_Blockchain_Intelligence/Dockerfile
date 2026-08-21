FROM python:3.11-slim AS base

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir "."

COPY . .

ENV PYTHONPATH=/app
ENV APP_ENV=production

EXPOSE 8801

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8801/health || exit 1

ENTRYPOINT ["python", "-m", "cli.main"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8801"]
