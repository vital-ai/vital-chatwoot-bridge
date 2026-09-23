# Use Python 3.12 slim image as base
FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PORT=8000 \
    LOG_LEVEL=INFO

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        unixodbc \
        unixodbc-dev \
        libodbccr2 \
        libodbc2 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt ./

COPY vital_env.env vital_env.env
COPY vitalhome vitalhome

ENV VITALHOME=/app/vitalhome

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

RUN python -c "from vital_ai_vitalsigns.vitalsigns import VitalSigns; VitalSigns()"

# Copy application code
COPY vital_chatwoot_bridge/ ./vital_chatwoot_bridge/

# Create non-root user for security
# (VitalSigns registry cache is written as root by the warm-up above with
# 0600 perms; hand it to appuser so it can be read and refreshed at runtime)
RUN groupadd -r appuser && useradd -r -g appuser appuser \
    && chown -R appuser:appuser /app \
    && chown -R appuser:appuser "$(python -c 'import os, vital_ai_vitalsigns; print(os.path.dirname(vital_ai_vitalsigns.__file__))')/_vitalsigns_cache"
USER appuser

# Expose port
EXPOSE $PORT

# Run the application
CMD ["python", "-m", "vital_chatwoot_bridge.main"]
