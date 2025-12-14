# Use Python 3.11 slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies (needed for psycopg2 and PDF tools)
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python libraries
# Combined dependencies for Bot, PDF Tools, and CSV Importer
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

# Copy source code
COPY ./src /app/src
COPY ./data /app/data

# Expose port for Flask
EXPOSE 5000

# Default command: Starts the WhatsApp bot automatically
CMD ["python", "src/whatsapp_bot.py"]
