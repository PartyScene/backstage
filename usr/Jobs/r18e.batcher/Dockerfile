# Test stage
FROM python:3.13-slim

# Install system dependencies
# RUN apt-get update && apt-get install -y --no-install-recommends \
#     build-essential \
#     && rm -rf /var/lib/apt/lists/*

RUN pip3 install rloop surrealdb transformers msgpack faststream[rabbit] faststream[clis] accelerate 
RUN pip3 install torch torchvision torchaudio


COPY . .

CMD [ "faststream", "r18e:app" ]