# Use a Python image with relevant dependencies
# FROM python:3.12-rc-bookworm
FROM python:alpine3.19

WORKDIR /app

# Copy the service-specific files
COPY . .

# Set PYTHONPATH to include shared libraries
ENV PYTHONPATH="/app/shared:${PYTHONPATH}"

# Install dependencies when the container starts
CMD pip install -r /app/shared/requirements.txt && pip install -r requirements.txt && python run.py