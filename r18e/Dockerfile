# Test stage
FROM python:3.11-slim AS base

WORKDIR /r18e

# Set PYTHONPATH for shared libraries
ENV PYTHONPATH="/"

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*


# Copy requirements files
COPY r18e ./
COPY shared /shared/
COPY tests/requirements-test.txt /tests/requirements-test.txt


# Install dependencies
RUN pip install --no-cache-dir -r /shared/requirements.txt \
    && pip install --no-cache-dir -r /tests/requirements-test.txt \
    && pip install --no-cache-dir -r ./requirements.txt

COPY auth /auth/

FROM base AS test

# Copy application code and tests
COPY tests/conftest.py /tests/conftest.py
COPY tests/r18e/ /tests/r18e/
COPY tests/pytest.ini /tests/pytest.ini


# Run tests
CMD ["pytest", "--disable-warnings", "/tests", "-v"]

# Main stage
FROM base AS stage_production

WORKDIR /r18e

# Set PYTHONPATH for shared libraries
# ENV PYTHONPATH="/shared:${PYTHONPATH}"

# Copy application code
COPY --from=base /usr/local/lib/python3.14/site-packages /usr/local/lib/python3.14/site-packages
COPY r18e/ .
COPY shared/ /shared/

# install deps
RUN pip install --no-cache-dir -r /shared/requirements.txt \
    && pip install --no-cache-dir -r ./requirements.txt

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


FROM stage_production AS prod

# Run with Granian which is a Rust based ASGI server with benchmarks exceeding Hypercorn
CMD ["python3", "-m", "granian", \
     "--loop", "uvloop", \
     "--host", "0.0.0.0", \
     "--port", "5510", \
     "--workers", "4", \
     "--interface", "asgi", \
     "--no-log", \
     "--task-impl", "rust", \
     "--runtime-mode", "mt", \
     "run:app"]