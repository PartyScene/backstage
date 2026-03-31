FROM python:3.12-slim
WORKDIR /app

COPY usr/Jobs/event-recap/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY usr/Jobs/event-recap/recap.py .
COPY shared/workers/novu/ ./shared/workers/novu/

CMD ["python", "recap.py"]
