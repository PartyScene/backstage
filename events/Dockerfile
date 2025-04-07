# Test stage
FROM python:3.11-slim AS test

WORKDIR /events

# Set PYTHONPATH for shared libraries
ENV PYTHONPATH="/"

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements files
COPY events/ ./
COPY shared/ /shared/
COPY auth/ /auth/

# Copy application code and tests
COPY tests/conftest.py /tests/conftest.py
COPY tests/requirements-test.txt /tests/requirements-test.txt
COPY tests/events/ /tests/events/
COPY tests/pytest.ini /tests/pytest.ini

# Install dependencies
RUN pip install --no-cache-dir -r /shared/requirements.txt \
    && pip install --no-cache-dir -r /tests/requirements-test.txt

# Run tests
CMD ["pytest", "--disable-warnings", "/tests", "-v"]

# Main stage
FROM python:3.11-slim AS prod

WORKDIR /events

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Set PYTHONPATH for shared libraries
# ENV PYTHONPATH="/shared:${PYTHONPATH}"

# Copy application code
COPY --from=test /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY events/ ./
COPY shared/ /shared/

# install deps
RUN pip install --no-cache-dir -r /shared/requirements.txt

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV QUART_APP=run:app
ENV QUART_ENV=production
ENV PYTHONPATH="/"

# Run as non-root user
RUN useradd -m myuser
USER myuser

# Expose port
EXPOSE 5510


# Run with Granian which is a Rust based ASGI server with benchmarks exceeding Hypercorn
CMD ["python3", "-m", "granian", \
     "--loop", "rloop", \
     "--host", "0.0.0.0", \
     "--port", "5510", \
     "--workers", "1", \
     "--no-log", \
     "--task-impl", "rust", \
     "--runtime-mode", "mt", \
     "run:app"]