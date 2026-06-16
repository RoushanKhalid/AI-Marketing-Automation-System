# Use official Python runtime as base image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DB_PATH=/data/campaigns.db \
    SCHEDULER_INTERVAL_SECONDS=30

# Set working directory inside the container
WORKDIR /workspace

# Install system dependencies (curl is used for container health check)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY app/ ./app/
COPY static/ ./static/

# Create data directory for persistent SQLite database volume
RUN mkdir -p /data

# Expose server port
EXPOSE 8000

# Health check to ensure API is responsive
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

# Command to run application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
