FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Render usa $PORT, Docker locale usa 8000 come default
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
