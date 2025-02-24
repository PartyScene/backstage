# Test stage
FROM python:3.11-slim as test

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Set PYTHONPATH for shared libraries
ENV PYTHONPATH="/app/shared:${PYTHONPATH}"

# Copy requirements files
COPY requirements.txt .
COPY ../requirements-test.txt .
COPY ../shared/requirements.txt ./shared-requirements.txt

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir -r requirements-test.txt \
    && pip install --no-cache-dir -r shared-requirements.txt

# Copy application code and tests
COPY . .
COPY ../tests ./tests
COPY ../shared ./shared

# Run tests
RUN python -m pytest tests/auth/test_authentication.py -v

# Main stage
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Set PYTHONPATH for shared libraries
ENV PYTHONPATH="/app/shared:${PYTHONPATH}"

# Copy and install service requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV QUART_APP=run:app
ENV QUART_ENV=production

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