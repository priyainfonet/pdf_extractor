# Same image serves two roles in docker-compose.yml: the API server
# (uvicorn) and the Celery worker — they differ only in the container's
# command, not the image, so there's one Dockerfile for both.

FROM python:3.12-slim

WORKDIR /app

# System deps: gcc for anything that still needs to compile, libpq for
# psycopg2 (Postgres driver) at runtime.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-docker.txt .
RUN pip install --no-cache-dir -r requirements-docker.txt

COPY . .

RUN mkdir -p storage/uploads storage/outputs

EXPOSE 8000

# Default command runs the API server; docker-compose.yml overrides this
# for the `worker` service to run Celery instead.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
