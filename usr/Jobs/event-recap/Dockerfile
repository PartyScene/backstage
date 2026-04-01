FROM python:3.12-slim
WORKDIR /app

COPY usr/Jobs/event-recap/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY usr/Jobs/event-recap/recap.py .
COPY shared/__init__.py ./shared/__init__.py
COPY shared/workers/__init__.py ./shared/workers/__init__.py
COPY shared/workers/novu/ ./shared/workers/novu/
COPY shared/utils/signer.py ./shared/utils/signer.py
RUN touch ./shared/utils/__init__.py

CMD ["python", "recap.py"]
