FROM python:3.11-slim-bookworm

# Critical environment variables for Python and JobRadar
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    JOBRADAR_HOME=/data \
    PORT=8000

WORKDIR /app

# Install base system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy the source code
COPY . .

# Install JobRadar and all its optional dependencies (PDF, Excel, CV parsing)
# Also force the installation of scrapling for restricted sources
RUN pip install --no-cache-dir -e .[pdf,parse,excel] scrapling

# Install browser dependencies:
# 1. Playwright (for rendering CVs as PDF)
# 2. Scrapling (for evading anti-bot measures on InfoJobs, LinkedIn, etc.)
RUN playwright install --with-deps chromium && \
    scrapling install

# Create the directory where the database and generated documents will reside
RUN mkdir -p /data

EXPOSE 8000

# Ensure that the data persists across container restarts
VOLUME ["/data"]

# Run the dashboard listening on all interfaces so it's accessible from outside the container
CMD ["jobradar", "serve", "--host", "0.0.0.0", "--port", "8000"]