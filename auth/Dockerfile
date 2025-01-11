# Use a Python image with relevant dependencies
FROM python:alpine3.19

WORKDIR /app

# Copy service-specific requirements to cache dependencies
COPY requirements.txt /app/requirements.txt

# Install service-specific dependencies during build
RUN pip install -r /app/requirements.txt

# Copy the rest of the application files
COPY . .

# Set PYTHONPATH to include shared libraries
ENV PYTHONPATH="/app/shared:${PYTHONPATH}"

# Install shared dependencies at runtime
CMD pip install -r /app/shared/requirements.txt && python run.py