FROM python:3.13-slim

# Print logs immediately (no buffering), and don't write .pyc files into the image.
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install dependencies first: Docker caches this layer, so code-only changes rebuild much faster.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Cloud Run tells the container which port to listen on through $PORT.
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}
