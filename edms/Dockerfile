FROM python:3.12-slim

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install EDMS package in editable mode so the volume mount in
# docker-compose.yml (./edms:/app/edms) lets host edits propagate
# live to the running container — `pip install -e` drops a .pth file
# in site-packages pointing back at /app/edms/src/edms, and uvicorn
# --reload picks up the file changes through the mount.
# Matches the Verity service Dockerfile pattern.
COPY edms/ /app/edms/
RUN pip install --no-cache-dir -e /app/edms/

# Seed documents are mounted as a volume for the upload-local endpoint
# (used by the seed script to bulk-upload generated documents)

EXPOSE 8002

CMD ["uvicorn", "edms.service.main:app", "--host", "0.0.0.0", "--port", "8002", "--reload"]
