FROM python:3.12-slim
WORKDIR /app

COPY usr/Jobs/event-reminder/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY usr/Jobs/event-reminder/reminder.py .
COPY shared/workers/novu/ ./shared/workers/novu/

CMD ["python", "reminder.py"]
