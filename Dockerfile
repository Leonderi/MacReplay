# Use Python 3.11 slim image as base
FROM python:3.11-slim AS base

# Set working directory
WORKDIR /app

# Install system dependencies including ffmpeg and curl for health checks
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create directories for data persistence
RUN mkdir -p /app/data /app/logs

# Copy Python dependencies files
COPY requirements.txt .
COPY requirements-dev.txt .

# Install runtime dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY app.py .
COPY stb.py .
COPY macreplay/ macreplay/
COPY templates/ templates/
COPY static/ static/

# Create non-root user for security
RUN useradd -m -u 1000 macreplay && \
    chown -R macreplay:macreplay /app

# Switch to non-root user
USER macreplay

# Set environment variables for containerized deployment
ENV HOST=0.0.0.0:8001
ENV CONFIG=/app/data/MacReplay.json
ENV DB_PATH=/app/data/channels.db
ENV PYTHONUNBUFFERED=1

# Expose the application port
EXPOSE 8001

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8001/ || exit 1

# Development image with test dependencies
FROM base AS dev
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY tests/ tests/
ENV PATH="/home/macreplay/.local/bin:${PATH}"
ENV PYTHONPATH="/app"

# Production image (default)
FROM base AS prod

# Run the application
CMD ["python", "app.py"] 
