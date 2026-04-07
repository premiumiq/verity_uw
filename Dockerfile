FROM python:3.12-slim

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Verity package in editable mode
COPY verity/ /app/verity/
RUN pip install --no-cache-dir -e /app/verity/

# Copy application code
COPY uw_demo/ /app/uw_demo/
COPY scripts/ /app/scripts/

# Both ports available — docker-compose.yml selects which to use per container
EXPOSE 8000 8001

# Default CMD is overridden in docker-compose.yml per container:
#   verity container:  uvicorn verity.main:app --port 8000
#   uw-demo container: uvicorn uw_demo.app.main:app --port 8001
CMD ["uvicorn", "verity.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
