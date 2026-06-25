FROM python:3.11-slim

WORKDIR /app

# system deps for pandas/numpy wheels are bundled; keep image lean
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# data dir for the SQLite file (mount a volume here in production to persist)
RUN mkdir -p /app/data

ENV PYTHONUNBUFFERED=1 \
    POLL_SECONDS=60 \
    SEED_START_DATE=2026-01-01 \
    SEED_INITIAL_CAPITAL=100000

EXPOSE 8000

# single always-on process: serves the API/dashboard AND runs the bot worker threads
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
