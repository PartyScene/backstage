# Test stage
FROM python:3.11-slim as test

WORKDIR /auth

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set PYTHONPATH for shared libraries
ENV PYTHONPATH="/auth:/auth/shared:${PYTHONPATH}"

# Copy requirements files
COPY auth .

COPY shared /shared/

# Copy application code and tests
COPY tests /tests/

# Install dependencies
RUN pip install  -r requirements.txt \
    && pip install -r /tests/requirements-test.txt

# I
RUN curl -sSf https://install.surrealdb.com | sh

# RUN surreal start --log debug --user root --pass root memory

# Run tests
# RUN python -m pytest tests/auth/test_authentication.py -v
# Start SurrealDB and keep container running
ENTRYPOINT surreal start --user root --pass root memory & pytest --disable-warnings /tests/auth -v

# # Main stage
# FROM python:3.11-slim

# WORKDIR /app

# # Install system dependencies
# RUN apt-get update && apt-get install -y --no-install-recommends \
#     build-essential \
#     && rm -rf /var/lib/apt/lists/*

# # Set PYTHONPATH for shared libraries
# ENV PYTHONPATH="/app/shared:${PYTHONPATH}"

# # Copy and install service requirements
# COPY requirements.txt .
# RUN pip install --no-cache-dir -r requirements.txt

# # Copy application code
# COPY . .

# # Set environment variables
# ENV PYTHONUNBUFFERED=1
# ENV QUART_APP=run:app
# ENV QUART_ENV=production

# # Run as non-root user
# RUN useradd -m myuser
# USER myuser

# # Expose port
# EXPOSE 5510

# # Run with Hypercorn
# CMD ["hypercorn", "run:app", \
#      "--bind", "0.0.0.0:5510", \
#      "--workers", "4", \
#      "--access-logfile", "-", \
#      "--error-logfile", "-", \
#      "--worker-class", "asyncio", \
#      "--keep-alive", "120"]