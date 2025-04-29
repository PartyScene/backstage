

# --- Stage 1: Builder ---
# Install dependencies and download the model. Depot will cache the outputs
# of these RUN commands aggressively across builds and machines.
FROM python:3.13-slim AS builder

# Set working directory
WORKDIR /app

# Set Hugging Face cache directory (avoids using user home dir)
# Depot respects standard ENV variables like this.
ENV HF_HOME=/opt/huggingface_cache
ENV PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on
# Pass VIT_MODEL_NAME at build time if you want flexibility
ARG VIT_MODEL_NAME="google/vit-base-patch16-224-in21k"

# Install necessary system packages. Depot caches the resulting layer.
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    libgl1 \
    libglib2.0-0 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy only the requirements file first. Depot uses this layer boundary for caching.
COPY requirements.txt .

# Install Python dependencies. Depot caches this layer based on requirements.txt content.
RUN pip install -r requirements.txt

# --- Download the Hugging Face model ---
# Depot caches this RUN layer based on the previous layers and the command itself.
# The downloaded model files inside HF_HOME become part of this cached layer.
RUN python -c "from transformers import ViTImageProcessor, ViTModel; import os; \
    model_id = os.environ.get('VIT_MODEL_NAME', '${VIT_MODEL_NAME}'); \
    hf_home = os.environ.get('HF_HOME'); \
    print(f'Downloading model {model_id} to {hf_home}') ; \
    ViTImageProcessor.from_pretrained(model_id, cache_dir=hf_home); \
    ViTModel.from_pretrained(model_id, cache_dir=hf_home); \
    print('Model download complete.')"

# --- Stage 2: Runtime ---
# Create the final, smaller image using artifacts cached by Depot.
FROM python:3.13-slim AS runtime

# Set working directory
WORKDIR /app

# Set Hugging Face cache directory - MUST match the builder stage
ENV HF_HOME=/opt/huggingface_cache
# Set PYTHONUNBUFFERED for better logging in containers
ENV PYTHONUNBUFFERED=1

# Copy necessary system libraries from the builder stage. Depot handles this efficiently.
COPY --from=builder /usr/lib/x86_64-linux-gnu/libglib-2.0.so.0 /usr/lib/x86_64-linux-gnu/
COPY --from=builder /usr/lib/x86_64-linux-gnu/libGL.so.1 /usr/lib/x86_64-linux-gnu/
# Add other libs if needed based on runtime errors

# Copy installed Python packages from the builder stage.
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy the populated Hugging Face model cache from the builder stage.
# Depot efficiently handles copying these potentially large directories using its cache.
COPY --from=builder ${HF_HOME} ${HF_HOME}

# Copy the application code LAST. Depot only rebuilds from here if app code changes.
COPY . .

# Command to run the application
# Assumes your Python script is named r18e.py
CMD ["faststream", "run", "r18e:app"]