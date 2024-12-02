# Use a Python image with relevant dependencies
FROM python:alpine3.19

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .
CMD ["python", "run.py"]