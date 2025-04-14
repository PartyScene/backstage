# Test stage
FROM python:3.11-slim AS test
WORKDIR /auth
ENV PYTHONPATH="/" 
# Re-evaluate if "/" is correct, maybe "/auth:/shared"?

# Install system dependencies FIRST (less likely to change)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy ONLY requirements files
COPY shared/requirements.txt /shared/requirements.txt
COPY auth/requirements.txt ./requirements.txt
COPY tests/requirements-test.txt /tests/requirements-test.txt

# Install dependencies using copied requirements
# Ensures this layer is cached as long as requirements don't change
RUN pip install --no-cache-dir -r /shared/requirements.txt \
    && pip install --no-cache-dir -r /tests/requirements-test.txt \
    && pip install --no-cache-dir -r ./requirements.txt

# Copy application and test code AFTER dependency installation
COPY shared/ /shared/
COPY auth/ .
COPY init/schema.surql /home/schema.surql 
# Consider placing within /auth or /shared if related
COPY tests/conftest.py /tests/conftest.py
COPY tests/auth/ /tests/auth/
COPY tests/pytest.ini /tests/pytest.ini

# Run tests
ENTRYPOINT ["pytest", "--disable-warnings", "/tests", "-v"]

# Main stage
FROM python:3.11-slim AS prod

WORKDIR /auth

# Install ONLY runtime system dependencies if needed (e.g., libpq5, NOT build-essential)
# RUN apt-get update && apt-get install -y --no-install-recommends libpq5 && rm -rf /var/lib/apt/lists/*

# Copy ONLY production requirements files from the source context
COPY --from=test /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY shared/requirements.txt /shared/requirements.txt
COPY auth/requirements.txt ./requirements.txt
# DO NOT copy test requirements

# Install ONLY production dependencies
# Use a virtual environment (optional but good practice) or install globally
# If any packages need build tools, consider a separate 'builder' stage before 'prod'
RUN pip install --no-cache-dir -r /shared/requirements.txt \
    && pip install --no-cache-dir -r ./requirements.txt

# Copy application code
COPY auth/ .
COPY shared/ /shared/
COPY init/schema.surql /home/schema.surql
 # Consider placing within /auth or /shared

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV QUART_APP=run:app
ENV QUART_ENV=production
# ENV PYTHONPATH="/auth:/shared" # Example: Adjust if necessary, or remove if structure allows
ENV PYTHONPATH="/"

# Run as non-root user
RUN useradd -m myuser
USER myuser

# Expose port
EXPOSE 5510

# Runtime Command (looks good - using granian with performance options)
# dynamically sets workers based on available cores
CMD ["sh", "-c", \
     "exec python3 -m granian \
     --loop uvloop \
     --host 0.0.0.0 \
     --port 5510 \
     --workers $(nproc) \
     --no-log \
     --task-impl rust \
     --interface asgi \
     --runtime-mode mt \
     run:app" \
    ]