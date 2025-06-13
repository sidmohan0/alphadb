# Use Python 3.11 slim-bullseye for optimal size/compatibility balance
# Rationale: slim-bullseye is debian-based (reliable), includes necessary build tools,
# and Python 3.11 has excellent async/await support for future WebSocket features
FROM python:3.11-slim-bullseye

# Install system dependencies for psycopg2 (PostgreSQL adapter)
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the ingestor script
COPY scripts/ingest.py .

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash trader
USER trader

# Default command
CMD ["python", "ingest.py"]