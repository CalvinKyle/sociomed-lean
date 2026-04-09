FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

# Create data directory for SQLite + catalog + quotes
RUN mkdir -p data/quotes

EXPOSE 5000

# Gunicorn: 2 sync workers is enough for WebHook workload
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:5000", \
     "--timeout", "30", "--access-logfile", "-", \
     "app.bot:app"]
