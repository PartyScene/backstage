FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Set PYTHONPATH for shared libraries
ENV PYTHONPATH="/app/shared:${PYTHONPATH}"

# Create directory for GCP credentials
RUN mkdir -p /root/.config/gcloud

# Copy shared files first
# COPY shared /app/shared/

# Copy and install service requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV QUART_APP=run:app
ENV QUART_ENV=production
ENV GOOGLE_APPLICATION_CREDENTIALS=/root/.config/gcloud/application_default_credentials.json

# # Run as non-root user
# RUN useradd -m myuser
# USER myuser

# Expose port
EXPOSE 5510

# Run with Hypercorn
CMD ["hypercorn", "run:app", \
     "--bind", "0.0.0.0:5510", \
     "--workers", "10", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "--worker-class", "uvloop", \
     "--keep-alive", "120"]