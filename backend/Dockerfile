# ReguMap-AI — Python Backend Dockerfile
# Classified: High-Criticality IA Engine (DO-326A Security Perimeter)

FROM python:3.12-slim

# Prevent Python from writing .pyc files and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

WORKDIR /app

# Install system dependencies (for building some python packages if needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
# We copy the entire backend directory into /app
COPY . .

# Create data directories if they don't exist
RUN mkdir -p data/vector_db data/graph data/logs data/audit/reports

# Expose the internal port (No host mapping)
EXPOSE 8000

# Start the API server
# We use uvicorn to serve the FastAPI app
CMD ["uvicorn", "api_pkg.main:app", "--host", "0.0.0.0", "--port", "8000"]
