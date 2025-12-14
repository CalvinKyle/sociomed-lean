# Use Python 3.11 slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies (for psycopg2 if needed)
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies in one layer
RUN pip install --no-cache-dir \
    pandas \
    sqlalchemy \
    psycopg2-binary \
    openpyxl \
    flask \
    requests \
    fpdf2 \
    beautifulsoup4 \
    pypdf \
    google-generativeai \
    python-dotenv

# Copy only the application code (data and db handled by volumes)
COPY app/ /app/

# Expose Flask port
EXPOSE 5001

# Run the WhatsApp bot with unbuffered output (better logs)
CMD ["python", "-u", "/app/whatsapp_bot.py"]

