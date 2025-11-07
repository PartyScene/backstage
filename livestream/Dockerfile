# RUN mkdir -p /root/.config/gcloud
# ENV GOOGLE_APPLICATION_CREDENTIALS=/root/.config/gcloud/application_default_credentials.json

# Test stage
FROM python:3.13-slim AS test

WORKDIR /livestream

# Set PYTHONPATH for shared libraries
ENV PYTHONPATH="/"

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements files
COPY shared/ /shared/
COPY tests/requirements-test.txt /tests/requirements-test.txt

# Install dependencies
RUN pip install --no-cache-dir -r /shared/requirements.txt \
    && pip install --no-cache-dir -r /tests/requirements-test.txt

# Copy requirements files
COPY livestream ./
COPY auth/ /auth/

# Copy application code and tests
COPY tests/conftest.py /tests/conftest.py

COPY tests/livestream/ /tests/livestream/
COPY tests/pytest.ini /tests/pytest.ini

# Run tests
CMD ["pytest", "--disable-warnings", "/tests", "-v"]

# Main stage
FROM python:3.13-slim AS prod

WORKDIR /livestream

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy application code
COPY livestream/ ./
COPY shared/ /shared/

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV QUART_APP=run:app
ENV QUART_ENV=production
ENV PYTHONPATH="/"

# Install dependencies (do this BEFORE switching user so executables go to /usr/local/bin)
RUN pip install --no-cache-dir -r /shared/requirements.txt \
    && pip install --no-cache-dir -r ./requirements.txt

# Run as non-root user (after all installations)
RUN useradd -m myuser
USER myuser

# Expose port
EXPOSE 5550

# Run with Granian which is a Rust based ASGI server with benchmarks exceeding Hypercorn
CMD ["python3", "-m", "granian", \
     "--loop", "uvloop", \
     "--host", "0.0.0.0", \
     "--port", "5550", \
     "--workers", "1", \
     "--no-log", \
     "--task-impl", "rust", \
     "--interface", "asgi", \
     "--runtime-mode", "mt", \
     "run:app"]