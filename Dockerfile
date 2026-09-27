# NexusAI backend image — serves both the API and the Celery worker
# (the running command is chosen per-service in docker-compose.yml).
FROM python:3.11-slim

# Prevent .pyc files and enable unbuffered stdout for clean container logs.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# System deps: build tools for native wheels, libpq for psycopg2, curl for healthchecks.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first for better layer caching.
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy application source.
COPY . .

EXPOSE 8000

# Default command runs the API; the worker service overrides this in compose.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
