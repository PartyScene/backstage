# Use a Python image with relevant dependencies
FROM python:3.12-rc-bookworm

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .
CMD ["python", "run.py"]