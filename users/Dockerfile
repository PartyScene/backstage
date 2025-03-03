# Test stage
FROM python:3.11-slim AS test

WORKDIR /users

# Set PYTHONPATH for shared libraries
ENV PYTHONPATH="/"

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements files
COPY tests/requirements-test.txt /tests/requirements-test.txt
COPY shared/ /shared/

# Install dependencies
RUN pip install --no-cache-dir -r /shared/requirements.txt \
    && pip install --no-cache-dir -r /tests/requirements-test.txt

COPY users/ ./
COPY auth/ /auth/

# Copy application code and tests
COPY tests/conftest.py /tests/conftest.py
COPY tests/users/ /tests/users/
COPY tests/pytest.ini /tests/pytest.ini

# Run tests
CMD ["pytest", "--disable-warnings", "/tests", "-v"]

# Main stage
FROM python:3.11-slim AS prod

WORKDIR /users

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Set PYTHONPATH for shared libraries
# ENV PYTHONPATH="/shared:${PYTHONPATH}"

# Copy application code
COPY users/ ./
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

# Run with Hypercorn
CMD ["hypercorn", "run:app", \
     "--bind", "0.0.0.0:5510", \
     "--workers", "4", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "--worker-class", "asyncio", \
     "--keep-alive", "120"]