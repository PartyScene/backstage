FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*


# Set PYTHONPATH for shared libraries
ENV PYTHONPATH="/app/shared:${PYTHONPATH}"

# Install shared requirements first
# RUN pip install --no-cache-dir -r shared/requirements.txt

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
     "--workers", "1", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "--worker-class", "asyncio", \
     "--keep-alive", "120"]