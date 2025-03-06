# Test stage
FROM python:3.11-slim AS test

WORKDIR /auth

# Set PYTHONPATH for shared libraries
ENV PYTHONPATH="/"

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# These dependencies should exist at the top layer for best caching practices
COPY shared/ /shared/
COPY tests/requirements-test.txt /tests/requirements-test.txt

# Install dependencies
RUN pip install --no-cache-dir -r /shared/requirements.txt \
    && pip install --no-cache-dir -r /tests/requirements-test.txt

# Copy requirements files
COPY auth/ .

# Copy application code and tests
COPY tests/conftest.py /tests/conftest.py
COPY tests/auth/ /tests/auth/
COPY tests/pytest.ini /tests/pytest.ini

# Run tests
ENTRYPOINT ["pytest", "--disable-warnings", "/tests", "-v"]

# Main stage
FROM python:3.11-slim as prod

WORKDIR /auth

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Set PYTHONPATH for shared libraries
# ENV PYTHONPATH="/shared:${PYTHONPATH}"

# Copy application code
COPY auth .
COPY shared/ /shared/
COPY init/schema.surql /home/schema.surql

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

# Run with Hypercorn
CMD ["hypercorn", "run:app", \
     "--bind", "0.0.0.0:5510", \
     "--workers", "4", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "--worker-class", "asyncio", \
     "--keep-alive", "120"]