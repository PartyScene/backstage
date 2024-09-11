# Use a Python image with relevant dependencies
FROM python:latest

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .
CMD ["python", "run.py"]