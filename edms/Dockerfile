FROM python:3.12-slim

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install EDMS package
COPY edms/ /app/edms/
RUN pip install --no-cache-dir /app/edms/

# Seed documents are mounted as a volume for the upload-local endpoint
# (used by the seed script to bulk-upload generated documents)

EXPOSE 8002

CMD ["uvicorn", "edms.service.main:app", "--host", "0.0.0.0", "--port", "8002", "--reload"]
